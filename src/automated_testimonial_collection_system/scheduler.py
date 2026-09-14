import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

SCRIPT_FOLDER = Path(__file__).resolve().parent

PROCESSOR_SCRIPT = SCRIPT_FOLDER / "process_submissions.py"
DASHBOARD_SCRIPT = SCRIPT_FOLDER / "weekly_dashboard.py"


def run_script(script_path, label):
    """Run one project script without stopping the scheduler if it fails."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting {label}...")

    try:
        subprocess.run(
            [sys.executable, str(script_path)],
            check=True,
        )
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {label} finished.")

    except subprocess.CalledProcessError as error:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {label} failed: {error}")


def run_sentiment_pipeline():
    run_script(PROCESSOR_SCRIPT, "sentiment pipeline")


def run_weekly_dashboard():
    run_script(DASHBOARD_SCRIPT, "weekly dashboard")


# Run the sentiment pipeline at 5 minutes past every hour.
schedule.every().hour.at(":05").do(run_sentiment_pipeline)

# Run the dashboard each Monday at 9:00 AM, using your computer's local time.
schedule.every().monday.at("09:00").do(run_weekly_dashboard)

print("Scheduler is running.")
print("Sentiment pipeline: every hour at :05")
print("Weekly dashboard: every Monday at 09:00")
print("Press Ctrl+C to stop.")

while True:
    schedule.run_pending()
    time.sleep(30)
