import os
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage

from airtable_client import TESTIMONIALS_TABLE, get_all_records

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
OWNER_EMAIL = os.getenv("OWNER_EMAIL", SMTP_USER)
OWNER_NAME = os.getenv("OWNER_NAME", "there")


def previous_month_label():
    """Return the 'Month' label (e.g. 'August 2026') matching how Testimonials stores it."""
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    return last_day_prev_month.strftime("%B %Y")


def get_top_testimonials(limit=5):
    """Return up to `limit` testimonials from last month, highest rated first."""
    month_label = previous_month_label()
    testimonials = [
        record
        for record in get_all_records(TESTIMONIALS_TABLE)
        if record["fields"].get("Month") == month_label
    ]
    testimonials.sort(key=lambda r: r["fields"].get("Rating", 0), reverse=True)
    return testimonials[:limit], month_label


def format_digest_email(testimonials, month_label):
    lines = []
    for i, record in enumerate(testimonials, start=1):
        fields = record["fields"]
        text = fields.get("Formatted Testimonial", "")
        name = fields.get("Customer Name", "Anonymous")
        product = fields.get("Product or Service", "")
        lines.append(f'{i}. "{text}" - {name}, {product}')

    return f"""Hi {OWNER_NAME},

Here are your best customer testimonials from {month_label}:

{chr(10).join(lines)}

These are ready to use on your website, social media, or marketing materials.

The Brew & Bloom Automation System
"""


def send_monthly_digest():
    testimonials, month_label = get_top_testimonials()

    if not testimonials:
        print(f"No positive testimonials found for {month_label}. Skipping digest.")
        return

    if not all([SMTP_USER, SMTP_PASSWORD, FROM_EMAIL, OWNER_EMAIL]):
        print("SMTP is not configured; digest not sent.")
        return

    message = EmailMessage()
    message["Subject"] = (
        f"Brew & Bloom: Your Top {len(testimonials)} Testimonials This Month"
    )
    message["From"] = FROM_EMAIL
    message["To"] = OWNER_EMAIL
    message.set_content(format_digest_email(testimonials, month_label))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)
        print(
            f"Monthly digest sent for {month_label} with {len(testimonials)} testimonial(s)."
        )
    except Exception as error:
        print(f"Monthly digest could not be sent: {error}")


if __name__ == "__main__":
    send_monthly_digest()
