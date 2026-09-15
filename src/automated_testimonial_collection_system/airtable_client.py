import os
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
load_dotenv(PACKAGE_DIR / ".env", override=True)

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID]):
    raise RuntimeError(
        "Missing AIRTABLE_TOKEN or AIRTABLE_BASE_ID.\n"
        f"Looked for a .env file at: {PACKAGE_DIR / '.env'}"
    )

HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}

# Table names, defined once so every script refers to the same strings.
SUBMISSIONS_TABLE = "Submissions"
TESTIMONIALS_TABLE = "Testimonials"
FOLLOW_UPS_TABLE = "Follow-ups"
SUMMARY_TABLE = "Summary"

# 429 = rate limited. 5xx = Airtable's own infrastructure hiccuping.
# Both are worth a retry; anything else (400, 401, 403, 404...) is a real
# problem with the request itself and retrying won't fix it.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def table_url(table_name):
    """Return the Airtable API URL for one table."""
    return (
        f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{quote(table_name, safe='')}"
    )


def airtable_request(method, url, **kwargs):
    """
    Make an Airtable request, retrying on rate limits and Airtable-side
    errors (with backoff), and raising immediately on anything else.
    """
    last_error = None

    for attempt in range(MAX_ATTEMPTS):
        response = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)

        if response.ok:
            return response.json()

        last_error = RuntimeError(
            f"Airtable request failed ({response.status_code}): {response.text}"
        )

        is_last_attempt = attempt == MAX_ATTEMPTS - 1
        if response.status_code not in RETRYABLE_STATUS_CODES or is_last_attempt:
            raise last_error

        retry_after = response.headers.get("Retry-After")
        wait_seconds = float(retry_after) if retry_after else (2**attempt)
        print(
            f"  Airtable returned {response.status_code}; "
            f"retrying in {wait_seconds:.0f}s "
            f"(attempt {attempt + 1}/{MAX_ATTEMPTS})..."
        )
        time.sleep(wait_seconds)

    raise last_error


def get_all_records(table_name, filter_by_formula=None):
    """Fetch every record from one table, across all pages."""
    all_records = []
    params = {"pageSize": 100}
    if filter_by_formula:
        params["filterByFormula"] = filter_by_formula

    while True:
        data = airtable_request("GET", table_url(table_name), params=params)
        all_records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset

    return all_records


def create_record(table_name, fields):
    """Create one Airtable record."""
    return airtable_request("POST", table_url(table_name), json={"fields": fields})


def update_record(table_name, record_id, fields):
    """Update one Airtable record."""
    return airtable_request(
        "PATCH", f"{table_url(table_name)}/{record_id}", json={"fields": fields}
    )
