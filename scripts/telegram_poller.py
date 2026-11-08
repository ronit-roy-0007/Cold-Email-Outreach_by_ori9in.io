"""
Telegram Long-Polling Runner for IntentLead AI.
Allows receiving Telegram commands (/findleads, /status, /export_csv, /showpriority, /card)
directly on your local machine without needing public webhook tunnels (ngrok) or complex setup.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request
import urllib.error

from app.config import get_settings
from app.db import SessionLocal
from app.services.telegram_bot import handle_telegram_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telegram_poller")


def send_reply(token: str, chat_id: int | str, text: str, buttons: list | None = None) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as exc:
        logger.error("Failed to send reply to Telegram: %s", exc)


def answer_callback_query(token: str, callback_query_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as exc:
        logger.error("Failed to answer callback query: %s", exc)


def run_poller():
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    allowed_user_id = str(settings.TELEGRAM_ALLOWED_USER_ID or "")

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env! Exiting.")
        sys.exit(1)

    logger.info("Starting Telegram Poller for agency '%s'...", settings.AGENCY_NAME)
    logger.info("Authorized Telegram User ID: %s", allowed_user_id)
    logger.info("Waiting for Telegram commands (/findleads, /status, /export_csv, /showpriority)...")

    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"

    while True:
        try:
            req_url = f"{poll_url}?offset={offset}&timeout=20"
            req = urllib.request.Request(req_url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for update in data.get("result", []):
                update_id = update["update_id"]
                offset = update_id + 1

                try:
                    with SessionLocal() as db:
                        res = handle_telegram_update(update, db, settings)
                        db.commit()
                        logger.info("Processed update %s: status=%s", update_id, res.get("status"))

                        # If this was a button click (callback_query)
                        if "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb.get("id")
                            msg = res.get("message") or res.get("reply") or "Updated"
                            if cb_id:
                                answer_callback_query(token, cb_id, msg)
                            chat_id = cb.get("message", {}).get("chat", {}).get("id")
                            reply_text = res.get("reply") or f"📝 {msg}"
                            if chat_id:
                                send_reply(token, chat_id, reply_text, buttons=res.get("buttons"))

                        # If this was a text message
                        elif "message" in update and res.get("reply"):
                            chat_id = update["message"].get("chat", {}).get("id")
                            if chat_id:
                                send_reply(
                                    token,
                                    chat_id,
                                    res["reply"],
                                    buttons=res.get("buttons"),
                                )
                except Exception as exc:
                    logger.error("Error processing update %s: %s", update_id, exc)
                    chat_id = update.get("message", {}).get("chat", {}).get("id")
                    if chat_id:
                        send_reply(token, chat_id, f"⚠️ *Error processing request:*\n`{exc}`\n\nPlease send `/findleads` to retry.")

        except urllib.error.URLError as err:
            logger.warning("Network warning during poll: %s", err)
            time.sleep(3)
        except Exception as exc:
            logger.error("Unexpected error in poller loop: %s", exc)
            time.sleep(2)


if __name__ == "__main__":
    run_poller()
