import os
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[0]
load_dotenv(PROJECT_ROOT / ".env")

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

SUBMISSIONS_TABLE = "Submissions"
FOLLOW_UPS_TABLE = "Follow-ups"
SUMMARY_TABLE = "Summary"

if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
    raise RuntimeError("Missing AIRTABLE_TOKEN or AIRTABLE_BASE_ID in .env")

HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}


def table_url(table_name):
    return (
        f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{quote(table_name, safe='')}"
    )


def airtable_request(method, url, **kwargs):
    response = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)

    if not response.ok:
        raise RuntimeError(
            f"Airtable request failed ({response.status_code}): {response.text}"
        )

    return response.json()


def get_all_records(table_name):
    """Retrieve all records from one Airtable table, including every page."""
    records = []
    params = {"pageSize": 100}

    while True:
        data = airtable_request(
            "GET",
            table_url(table_name),
            params=params,
        )
        records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break

        params["offset"] = offset

    return records


def parse_airtable_date(value):
    """Convert Airtable date or date-time text to a Python date."""
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def last_completed_week():
    """
    Return Monday through Sunday for the most recently completed week.

    For example, when run on Monday, it reports the previous Monday-Sunday.
    """
    today = date.today()
    week_ending = today - timedelta(days=today.weekday() + 1)
    week_starting = week_ending - timedelta(days=6)
    return week_starting, week_ending


def is_in_period(value, start_date, end_date):
    record_date = parse_airtable_date(value)
    return record_date is not None and start_date <= record_date <= end_date


def get_follow_ups_sent(start_date, end_date):
    """Count follow-up emails successfully sent during the reporting period."""
    count = 0

    for record in get_all_records(FOLLOW_UPS_TABLE):
        fields = record["fields"]

        if fields.get("Follow-up Sent") is True and is_in_period(
            fields.get("Created At"), start_date, end_date
        ):
            count += 1

    return count


def find_summary_record(week_ending):
    """Return the existing summary record for this week, if it exists."""
    for record in get_all_records(SUMMARY_TABLE):
        stored_week_ending = parse_airtable_date(record["fields"].get("Week Ending"))

        if stored_week_ending == week_ending:
            return record

    return None


def create_or_update_summary(fields, week_ending):
    """Prevent duplicate dashboard rows when the script is run again."""
    existing_record = find_summary_record(week_ending)

    if existing_record:
        airtable_request(
            "PATCH",
            f"{table_url(SUMMARY_TABLE)}/{existing_record['id']}",
            json={"fields": fields},
        )
        print("Updated the existing weekly summary.")
    else:
        airtable_request(
            "POST",
            table_url(SUMMARY_TABLE),
            json={"fields": fields},
        )
        print("Created a new weekly summary.")


def build_weekly_dashboard():
    week_starting, week_ending = last_completed_week()

    submissions = [
        record
        for record in get_all_records(SUBMISSIONS_TABLE)
        if is_in_period(
            record["fields"].get("Submitted At"),
            week_starting,
            week_ending,
        )
    ]

    source_counts = Counter()
    sentiment_counts = Counter()
    ratings = []
    duplicates_caught = 0

    for record in submissions:
        fields = record["fields"]

        source = fields.get("Source", "").strip().lower()
        sentiment = fields.get("Sentiment Score", "").strip()
        status = fields.get("Status", "")

        source_counts[source] += 1
        sentiment_counts[sentiment] += 1

        if status == "Duplicate":
            duplicates_caught += 1

        rating = fields.get("Rating")
        if isinstance(rating, (int, float)):
            ratings.append(rating)

    average_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0
    follow_ups_sent = get_follow_ups_sent(week_starting, week_ending)

    summary_fields = {
        "Week Starting": week_starting.isoformat(),
        "Week Ending": week_ending.isoformat(),
        "Total Submissions": len(submissions),
        "Email Form Submissions": source_counts["email-form"],
        "QR Code Submissions": source_counts["qr-code"],
        "Positive Submissions": sentiment_counts["Positive"],
        "Neutral Submissions": sentiment_counts["Neutral"],
        "Negative Submissions": sentiment_counts["Negative"],
        "Average Rating": average_rating,
        "Duplicates Caught": duplicates_caught,
        "Follow-ups Sent": follow_ups_sent,
    }

    create_or_update_summary(summary_fields, week_ending)

    print(f"Dashboard period: {week_starting} to {week_ending}")
    print(f"Total submissions: {len(submissions)}")
    print(f"Average rating: {average_rating}")
    print(f"Follow-ups sent: {follow_ups_sent}")


if __name__ == "__main__":
    build_weekly_dashboard()
