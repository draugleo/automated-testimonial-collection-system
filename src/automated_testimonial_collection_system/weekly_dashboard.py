from collections import Counter
from datetime import date, datetime, timedelta

from airtable_client import (
    FOLLOW_UPS_TABLE,
    SUBMISSIONS_TABLE,
    SUMMARY_TABLE,
    create_record,
    get_all_records,
    update_record,
)


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


def find_summary_record(summary_records, week_ending):
    """Return the existing summary record for this week, if it exists."""
    for record in summary_records:
        stored_week_ending = parse_airtable_date(record["fields"].get("Week Ending"))

        if stored_week_ending == week_ending:
            return record

    return None


def create_or_update_summary(fields, week_ending):
    """Prevent duplicate dashboard rows when the script is run again."""
    existing_record = find_summary_record(get_all_records(SUMMARY_TABLE), week_ending)

    if existing_record:
        update_record(SUMMARY_TABLE, existing_record["id"], fields)
        print("Updated the existing weekly summary.")
    else:
        create_record(SUMMARY_TABLE, fields)
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
