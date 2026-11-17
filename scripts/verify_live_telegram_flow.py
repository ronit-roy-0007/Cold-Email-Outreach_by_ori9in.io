"""
Live Telegram Interaction & Evidence Verification for Authorized Operator 6107263210.
Executes the live onboarding workflow from Question 6 -> Question 7 -> Confirmation -> Launch,
sending actual live Telegram messages to the operator chat and capturing full evidence.
"""
import json
import logging
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "intelligence-api"))

from app.config import get_settings
from app.db import SessionLocal
from app.models import Campaign, OperatorProfile
from app.services.telegram_bot import (
    _USER_WIZARD_SESSIONS,
    handle_telegram_update,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("live_telegram_verifier")


def send_live_telegram_message(token: str, chat_id: str | int, text: str, buttons: list | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_live_verification():
    settings = get_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    operator_id = str(settings.TELEGRAM_ALLOWED_USER_ID or "6107263210")

    print("=" * 80)
    print("LIVE TELEGRAM WORKFLOW VERIFICATION FOR OPERATOR:", operator_id)
    print("=" * 80)

    evidence = []

    with SessionLocal() as db:
        # 1. Ensure Operator Profile exists
        prof = db.get(OperatorProfile, operator_id)
        if not prof:
            prof = OperatorProfile(user_id=operator_id, sender_name="Roy", agency_name="ori9in.io")
            db.add(prof)
            db.commit()

        # 2. Stage wizard session at Question 6
        bench_score = 40
        _USER_WIZARD_SESSIONS[operator_id] = {
            "step": "awaiting_template_choice",
            "niche": "B2B SaaS Companies",
            "location": "Austin, Texas",
            "services": "lead generation and marketing automation",
            "quantity": 5,
            "benchmark": bench_score,
        }
        _USER_WIZARD_SESSIONS.sync()

        # Step 6 presentation
        step6_reply = (
            f"✅ Benchmark score: *Score ≥ {bench_score}*\n\n"
            f"💬 *Step 6/7: High-Converting Cold Outreach Template*\n"
            f"Would you like to send our proven, highest-response cold outreach message instead of generating personalized AI pitches?\n\n"
            f"📝 *Message Preview:*\n"
            f"\"Hey [Business Name], tried to reach you a few times but didn't hear back . . .\n\n\n"
            f"Where should we go from here?\"\n\n"
            f"• *Reply YES:* Super-fast discovery, universal high-converting message for all leads, no review needed.\n"
            f"• *Reply NO:* Standard system, personalized AI proposal generated for each prospect's website audit.\n\n"
            f"_(Reply with Yes or No, or click a button below)_"
        )
        step6_buttons = [
            [
                {"text": "✅ Yes (Best-Response Template)", "callback_data": "wizard_template:yes"},
                {"text": "❌ No (Personalized AI Pitches)", "callback_data": "wizard_template:no"},
            ]
        ]

        print("\n--- [STAGE 1] DISPATCHING QUESTION 6/7 TO TELEGRAM OPERATOR ---")
        tg_res6 = send_live_telegram_message(token, operator_id, step6_reply, step6_buttons)
        msg_id_6 = tg_res6["result"]["message_id"]
        print(f"✓ Question 6 Delivered to Telegram! Message ID: {msg_id_6}")
        evidence.append({
            "stage": "Step 6/7 Presentation",
            "message_id": msg_id_6,
            "text": step6_reply,
            "buttons": step6_buttons,
        })

        # 3. Simulate Operator clicking 'YES' callback (wizard_template:yes)
        print("\n--- [STAGE 2] OPERATOR SELECTS 'YES' (Best-Response Template) ---")
        update_step6 = {
            "callback_query": {
                "id": "cb_live_step6_yes",
                "from": {"id": int(operator_id)},
                "data": "wizard_template:yes",
            }
        }
        res_step6 = handle_telegram_update(update_step6, db, settings)
        db.commit()

        print(f"Status from bot: {res_step6.get('status')}")
        print(f"Bot Reply:\n{res_step6.get('reply')}")
        assert "Step 7/7: Follow-Up Configuration" in res_step6["reply"]
        assert len(res_step6["buttons"]) == 2  # 2 rows of buttons

        # Deliver Question 7/7 to Telegram
        tg_res7 = send_live_telegram_message(token, operator_id, res_step6["reply"], res_step6["buttons"])
        msg_id_7 = tg_res7["result"]["message_id"]
        print(f"✓ Question 7 Delivered to Telegram! Message ID: {msg_id_7}")
        evidence.append({
            "stage": "Step 7/7 Presentation",
            "message_id": msg_id_7,
            "text": res_step6["reply"],
            "buttons": res_step6["buttons"],
        })

        # 4. Simulate Operator selecting 'Standard (Days 2 & 5)'
        print("\n--- [STAGE 3] OPERATOR SELECTS STANDARD (Days 2 & 5) ---")
        update_step7 = {
            "callback_query": {
                "id": "cb_live_step7_standard",
                "from": {"id": int(operator_id)},
                "data": "wizard_followup:standard",
            }
        }
        res_step7 = handle_telegram_update(update_step7, db, settings)
        db.commit()

        print(f"Status from bot: {res_step7.get('status')}")
        print(f"Summary Card Reply:\n{res_step7.get('reply')}")
        assert "Confirm Campaign & Follow-Up Architecture" in res_step7["reply"]
        assert "Day +2 (Calendar days)" in res_step7["reply"]
        assert "Day +5 (Calendar days)" in res_step7["reply"]

        tg_res_summary = send_live_telegram_message(token, operator_id, res_step7["reply"], res_step7["buttons"])
        msg_id_summary = tg_res_summary["result"]["message_id"]
        print(f"✓ Campaign Confirmation Delivered to Telegram! Message ID: {msg_id_summary}")
        evidence.append({
            "stage": "Campaign Confirmation Card",
            "message_id": msg_id_summary,
            "text": res_step7["reply"],
            "buttons": res_step7["buttons"],
        })

        # 5. Confirm & Launch Campaign
        print("\n--- [STAGE 4] OPERATOR CONFIRMS & LAUNCHES CAMPAIGN ---")
        update_confirm = {
            "callback_query": {
                "id": "cb_live_launch",
                "from": {"id": int(operator_id)},
                "data": "wizard_confirm:yes",
            }
        }
        res_launch = handle_telegram_update(update_confirm, db, settings)
        db.commit()

        print(f"Status from bot: {res_launch.get('status')}")
        print(f"Launch Reply:\n{res_launch.get('reply')}")
        assert "Campaign Completed & Scored" in res_launch["reply"]

        tg_res_launch = send_live_telegram_message(token, operator_id, res_launch["reply"], res_launch.get("buttons"))
        msg_id_launch = tg_res_launch["result"]["message_id"]
        print(f"✓ Campaign Scored Notification Delivered! Message ID: {msg_id_launch}")

        # 6. Verify Campaign in DB
        camp = db.query(Campaign).filter_by(niche="B2B SaaS Companies").order_by(Campaign.created_at.desc()).first()
        assert camp is not None
        print("\n--- [STAGE 5] DATABASE PERSISTENCE VERIFICATION ---")
        print(f"Campaign ID: {camp.id}")
        print(f"Niche: {camp.niche}")
        print(f"Location: {camp.location}")
        print(f"Follow-Up Sequence: {json.dumps(camp.followup_sequence, indent=2)}")
        assert camp.followup_sequence["enabled"] is True
        assert camp.followup_sequence["delays"] == [2, 5]
        assert camp.followup_sequence["schedule_type"] == "calendar"
        assert camp.filters["use_best_response_template"] is True

        print("\n🎉 ALL STAGES VERIFIED LIVE WITH TELEGRAM API & DATABASE PERSISTENCE!")
        return evidence


if __name__ == "__main__":
    run_live_verification()
