"""
IntentLead AI — Background Worker Daemon
Periodically processes scheduled follow-up outreach messages,
campaign progression, and background queue tasks with graceful shutdown handling.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone

from app.config import get_settings
from app.db import SessionLocal
from app.services.followup_engine import process_due_followups

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [worker] %(message)s",
)
logger = logging.getLogger("intentlead.worker")

running = True


def handle_shutdown(signum, frame):
    global running
    logger.info("Worker received shutdown signal (%s). Finishing current cycle and stopping...", signum)
    running = False


def run_worker_loop(interval_seconds: int = 30):
    global running
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    settings = get_settings()
    logger.info("Starting IntentLead AI Background Worker (Interval: %ds)...", interval_seconds)
    logger.info("Outreach dry-run: %s, Database: %s", settings.OUTREACH_DRY_RUN, settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "local")

    while running:
        try:
            with SessionLocal() as db:
                result = process_due_followups(db=db, settings=settings)
                executed = result.get("executed", 0)
                cancelled = result.get("cancelled", 0)
                failed = result.get("failed", 0)
                if executed > 0 or cancelled > 0 or failed > 0:
                    logger.info(
                        "Follow-up cycle completed: %d executed, %d cancelled, %d failed",
                        executed, cancelled, failed
                    )
        except Exception as exc:
            logger.error("Error during worker execution cycle: %s", exc, exc_info=True)

        # Sleep with sub-second wakeups to respond promptly to SIGTERM
        for _ in range(interval_seconds * 2):
            if not running:
                break
            time.sleep(0.5)

    logger.info("IntentLead AI Background Worker cleanly stopped.")


if __name__ == "__main__":
    interval = 30
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        interval = int(sys.argv[1])
    run_worker_loop(interval_seconds=interval)
