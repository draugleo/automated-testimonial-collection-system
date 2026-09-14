import json
import os
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from openai import OpenAI

env_path = Path(__file__).resolve().parents[0] / ".env"
load_dotenv(dotenv_path=env_path, override=True)

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

SUBMISSIONS_TABLE = "Submissions"
TESTIMONIALS_TABLE = "Testimonials"
FOLLOW_UPS_TABLE = "Follow-ups"

if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID, OPENAI_API_KEY]):
    raise RuntimeError(
        f"Missing required .env values. Looked for .env at: {env_path}\n"
        f"AIRTABLE_TOKEN loaded: {bool(AIRTABLE_TOKEN)}\n"
        f"AIRTABLE_BASE_ID loaded: {bool(AIRTABLE_BASE_ID)}\n"
        f"OPENAI_API_KEY loaded: {bool(OPENAI_API_KEY)}"
    )

HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
client = OpenAI(api_key=OPENAI_API_KEY)

SENTIMENT_PROMPT = """You are a sentiment analysis assistant. Analyze the following customer
feedback and return a JSON object with exactly these fields:

{{
  "sentiment": "Positive" or "Neutral" or "Negative",
  "reasoning": "one sentence explaining the classification",
  "testimonial": "if sentiment is Positive, rewrite the feedback as a clean, professional testimonial under 50 words. If not Positive, return an empty string."
}}

Feedback to analyze:
{feedback}

Rating: {rating} out of 5

Return only the JSON object. No preamble, no explanation outside the JSON."""


def table_url(table_name):
    """Return the Airtable API URL for one table."""
    return (
        f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{quote(table_name, safe='')}"
    )


def airtable_request(method, url, **kwargs):
    """Make an Airtable request and show its useful error details if it fails."""
    response = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)

    if not response.ok:
        raise RuntimeError(
            f"Airtable request failed ({response.status_code}): {response.text}"
        )

    return response.json()


def get_new_submissions():
    """Fetch every Submissions record where Status = 'New', across all pages."""
    all_records = []
    params = {
        "filterByFormula": "{Status} = 'New'",
        "pageSize": 100,
    }

    while True:
        data = airtable_request(
            "GET",
            table_url(SUBMISSIONS_TABLE),
            params=params,
        )
        all_records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break

        params["offset"] = offset

    return all_records


def is_duplicate(email):
    """A submission is a duplicate if its email appears more than once."""
    if not email:
        return False

    # Escape apostrophes so they do not break Airtable's formula.
    safe_email = email.replace("'", "\\'")
    params = {
        "filterByFormula": f"{{Email}} = '{safe_email}'",
        "pageSize": 100,
    }
    data = airtable_request(
        "GET",
        table_url(SUBMISSIONS_TABLE),
        params=params,
    )
    return len(data.get("records", [])) > 1


def analyze_sentiment(feedback_text, rating):
    """Call OpenAI and return the parsed sentiment dictionary, or None on failure."""
    prompt = SENTIMENT_PROMPT.format(
        feedback=feedback_text or "(No feedback provided)",
        rating=rating or "Not provided",
    )

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-5.6-luna",
                messages=[{"role": "user", "content": prompt}],
            )

            raw_content = response.choices[0].message.content.strip()
            result = json.loads(raw_content)

            if result.get("sentiment") not in {"Positive", "Neutral", "Negative"}:
                raise ValueError("The model returned an invalid sentiment value.")

            return result

        except json.JSONDecodeError:
            print("  OpenAI returned invalid JSON.")
            return None

        except Exception as error:
            if attempt == 0:
                print(f"  Analysis attempt failed: {error}. Retrying in 5 seconds...")
                time.sleep(5)
                continue

            print(f"  Sentiment analysis failed after retry: {error}")
            return None


def update_record(table_name, record_id, fields):
    """Update one Airtable record."""
    return airtable_request(
        "PATCH",
        f"{table_url(table_name)}/{record_id}",
        json={"fields": fields},
    )


def create_record(table_name, fields):
    """Create one Airtable record."""
    return airtable_request(
        "POST",
        table_url(table_name),
        json={"fields": fields},
    )


def send_slack_alert(customer_name, email, product, feedback_text):
    """
    Post a real-time alert to Slack for negative feedback.
    Returns True if the alert was sent; otherwise False.
    """
    if not SLACK_WEBHOOK_URL:
        print("  SLACK_WEBHOOK_URL not configured; alert not sent.")
        return False

    payload = {
        "text": (
            ":rotating_light: *Negative feedback received*\n"
            f"*Customer:* {customer_name or 'Unknown'}\n"
            f"*Email:* {email or 'Not provided'}\n"
            f"*Product/Service:* {product or 'Not specified'}\n"
            f"*Feedback:* {feedback_text or '(none)'}"
        )
    }

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        return True

    except Exception as error:
        print(f"  Slack alert could not be sent: {error}")
        return False


def send_follow_up_email(customer_name, recipient_email, sentiment):
    """
    Send a follow-up only when SMTP credentials are configured.
    Returns True if an email was sent; otherwise False.
    """
    if not all([SMTP_USER, SMTP_PASSWORD, FROM_EMAIL, recipient_email]):
        print(
            "  SMTP is not configured or the customer has no email; follow-up not sent."
        )
        return False

    name = customer_name or "there"

    if sentiment == "Negative":
        subject = "We're sorry your Brew & Bloom experience missed the mark"
        body = f"""Hi {name},

We're sorry to hear that your recent experience with Brew & Bloom was not what you expected.

We value your feedback and would appreciate the chance to make things right. Please reply to this email and tell us how we can help.

Warmly,
Brew & Bloom
"""
    else:
        subject = "Thank you for sharing your Brew & Bloom feedback"
        body = f"""Hi {name},

Thank you for sharing your feedback with Brew & Bloom.

We would love to know what could have made your experience even better. Please reply with any details you would like to share.

Warmly,
Brew & Bloom
"""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = FROM_EMAIL
    message["To"] = recipient_email
    message.set_content(body)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)

        return True

    except Exception as error:
        print(f"  Follow-up email could not be sent: {error}")
        return False


def create_testimonial(submission_id, fields, testimonial_text):
    """Copy a positive submission into the Testimonials table."""
    submitted_at = fields.get("Submitted At")
    month = (
        datetime.fromisoformat(submitted_at.replace("Z", "+00:00")).strftime("%B %Y")
        if submitted_at
        else datetime.now().strftime("%B %Y")
    )

    testimonial_fields = {
        "Customer Name": fields.get("Customer Name", ""),
        "Product or Service": fields.get("Product or Service", ""),
        "Formatted Testimonial": testimonial_text,
        "Rating": fields.get("Rating"),
        "Source": fields.get("Source", ""),
        "Month": month,
        "Linked Submission": [submission_id],
    }

    # Do not send empty optional fields to Airtable.
    testimonial_fields = {
        key: value
        for key, value in testimonial_fields.items()
        if value not in ("", None)
    }

    create_record(TESTIMONIALS_TABLE, testimonial_fields)


def create_follow_up(submission_id, fields, sentiment):
    """Create a Follow-ups record, send the customer an email, and alert Slack if negative."""
    customer_name = fields.get("Customer Name", "")
    email = fields.get("Email", "")
    product = fields.get("Product or Service", "")
    feedback_text = fields.get("Feedback Text", "")

    email_sent = send_follow_up_email(customer_name, email, sentiment)

    if sentiment == "Negative":
        send_slack_alert(customer_name, email, product, feedback_text)

    follow_up_fields = {
        "Customer Name": customer_name,
        "Email": email,
        "Original Feedback": feedback_text,
        "Follow-up Sent": email_sent,
        # Add this only if you add a Linked Submission field to Follow-ups:
        # "Linked Submission": [submission_id],
    }

    follow_up_fields = {
        key: value for key, value in follow_up_fields.items() if value not in ("", None)
    }

    create_record(FOLLOW_UPS_TABLE, follow_up_fields)


def process_submissions():
    submissions = get_new_submissions()
    print(f"Processing {len(submissions)} new submission(s)...")

    for record in submissions:
        record_id = record["id"]
        fields = record["fields"]

        email = fields.get("Email", "")
        feedback = fields.get("Feedback Text", "")
        rating = fields.get("Rating", "")

        try:
            if is_duplicate(email):
                update_record(
                    SUBMISSIONS_TABLE,
                    record_id,
                    {"Status": "Duplicate"},
                )
                print(f"  {email}: duplicate, skipped.")
                continue

            result = analyze_sentiment(feedback, rating)

            if result is None:
                update_record(
                    SUBMISSIONS_TABLE,
                    record_id,
                    {"Status": "Flagged"},
                )
                print(f"  {email}: sentiment analysis failed, flagged.")
                continue

            sentiment = result["sentiment"]
            reasoning = result.get("reasoning", "")
            testimonial = result.get("testimonial", "")

            if sentiment == "Positive":
                create_testimonial(record_id, fields, testimonial)

                update_record(
                    SUBMISSIONS_TABLE,
                    record_id,
                    {
                        "Sentiment Score": sentiment,
                        "Sentiment Reasoning": reasoning,
                        "Formatted Testimonial": testimonial,
                        "Testimonial Ready": True,
                        "Status": "Processed",
                    },
                )
                print(f"  {email}: positive, testimonial created.")

            elif sentiment == "Neutral":
                create_follow_up(record_id, fields, sentiment)

                update_record(
                    SUBMISSIONS_TABLE,
                    record_id,
                    {
                        "Sentiment Score": sentiment,
                        "Sentiment Reasoning": reasoning,
                        "Formatted Testimonial": "",
                        "Testimonial Ready": False,
                        "Status": "Processed",
                    },
                )
                print(f"  {email}: neutral, follow-up created.")

            else:  # Negative
                create_follow_up(record_id, fields, sentiment)

                update_record(
                    SUBMISSIONS_TABLE,
                    record_id,
                    {
                        "Sentiment Score": sentiment,
                        "Sentiment Reasoning": reasoning,
                        "Formatted Testimonial": "",
                        "Testimonial Ready": False,
                        "Status": "Flagged",
                    },
                )
                print(
                    f"  {email}: negative, follow-up created, Slack alerted, and flagged."
                )

        except Exception as error:
            print(f"  {email or record_id}: processing error: {error}")

            # Best effort: mark the submission for manual review.
            try:
                update_record(
                    SUBMISSIONS_TABLE,
                    record_id,
                    {"Status": "Flagged"},
                )
            except Exception as update_error:
                print(f"  Could not flag record {record_id}: {update_error}")


if __name__ == "__main__":
    process_submissions()
