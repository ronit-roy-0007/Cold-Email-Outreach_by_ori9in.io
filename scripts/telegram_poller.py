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
        safe_buttons = []
        for row in buttons:
            safe_row = []
            for btn in row:
                b = dict(btn)
                if "callback_data" in b:
                    cb_encoded = str(b["callback_data"]).encode("utf-8")
                    if len(cb_encoded) > 64:
                        logger.warning("Truncating callback_data exceeding 64 bytes: %s", b["callback_data"])
                        b["callback_data"] = cb_encoded[:64].decode("utf-8", errors="ignore")
                safe_row.append(b)
            safe_buttons.append(safe_row)
        payload["reply_markup"] = {"inline_keyboard": safe_buttons}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as exc:
        # Fallback 1: Plain text with buttons
        try:
            payload.pop("parse_mode", None)
            fallback_data = json.dumps(payload).encode("utf-8")
            fallback_req = urllib.request.Request(url, data=fallback_data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(fallback_req, timeout=15)
            logger.info("Sent reply to Telegram using plain text fallback after Markdown error")
        except Exception as fb_exc:
            # Fallback 2: Plain text without buttons (ensures user NEVER loses the text update)
            try:
                payload.pop("reply_markup", None)
                fallback_data2 = json.dumps(payload).encode("utf-8")
                fallback_req2 = urllib.request.Request(url, data=fallback_data2, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(fallback_req2, timeout=15)
                logger.info("Sent reply to Telegram using text-only fallback after markup error: %s", fb_exc)
            except Exception as fb_exc2:
                logger.error("Failed to send reply to Telegram: %s (fallback1: %s, fallback2: %s)", exc, fb_exc, fb_exc2)


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
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        logger.error("Failed to answer callback query: %s", exc)


def send_chat_action(token: str, chat_id: int | str, action: str = "typing") -> None:
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    payload = {
        "chat_id": chat_id,
        "action": action,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def sync_bot_commands(token: str) -> None:
    commands = [
        {"command": "findleads", "description": "Start client discovery in any city"},
        {"command": "settings", "description": "Connect/manage outreach Gmail accounts"},
        {"command": "live", "description": "Switch to real outbound email dispatch"},
        {"command": "dryrun", "description": "Switch to simulation/dry-run mode"},
        {"command": "mode", "description": "Check current outreach mode (LIVE vs DRY-RUN)"},
        {"command": "profile", "description": "View/update sender name and agency"},
        {"command": "status", "description": "View recent campaigns progress"},
        {"command": "export_csv", "description": "Export campaign leads spreadsheet"},
        {"command": "review", "description": "Review leads and AI pitches 1-by-1"},
        {"command": "clean_memory", "description": "Clear memory and reset bot fresh"},
        {"command": "help", "description": "Show help and all commands"},
    ]
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    data = json.dumps({"commands": commands}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Synced native Telegram commands menu: %s", resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to sync Telegram commands menu: %s", exc)


def run_poller():
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    allowed_user_id = str(settings.TELEGRAM_ALLOWED_USER_ID or "")

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env! Exiting.")
        sys.exit(1)

    sync_bot_commands(token)
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
                    # Instant UI Feedback: ACK button taps immediately & show typing indicator
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb.get("id")
                        chat_id = cb.get("message", {}).get("chat", {}).get("id")
                        if cb_id:
                            answer_callback_query(token, cb_id, "⚡ Processing...")
                        if chat_id:
                            send_chat_action(token, chat_id, "typing")
                    elif "message" in update:
                        chat_id = update["message"].get("chat", {}).get("id")
                        if chat_id:
                            send_chat_action(token, chat_id, "typing")

                    with SessionLocal() as db:
                        res = handle_telegram_update(update, db, settings)
                        db.commit()
                        logger.info("Processed update %s: status=%s", update_id, res.get("status"))

                        # If this was a button click (callback_query)
                        if "callback_query" in update:
                            cb = update["callback_query"]
                            chat_id = cb.get("message", {}).get("chat", {}).get("id")
                            msg = res.get("message") or res.get("reply") or "Updated"
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

        except (TimeoutError, urllib.error.URLError) as err:
            logger.debug("Poller timeout/cycle: %s", err)
            time.sleep(1)
        except Exception as exc:
            if "timed out" in str(exc).lower():
                logger.debug("Poller read timeout, cycling...")
                time.sleep(1)
            else:
                logger.error("Unexpected error in poller loop: %s", exc)
                time.sleep(2)


if __name__ == "__main__":
    run_poller()
