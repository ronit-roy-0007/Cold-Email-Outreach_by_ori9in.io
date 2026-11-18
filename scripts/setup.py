#!/usr/bin/env python3
"""
IntentLead AI — Interactive Setup & Onboarding Wizard
Guides first-time users through configuring their own database, admin account,
AI keys, Telegram bot, and email credentials.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import secrets
import sys

# Ensure intelligence-api is on python path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
API_DIR = WORKSPACE_ROOT / "apps" / "intelligence-api"
sys.path.insert(0, str(API_DIR))


def prompt_input(prompt: str, default: str = "") -> str:
    if default:
        formatted = f"{prompt} [{default}]: "
    else:
        formatted = f"{prompt}: "
    value = input(formatted).strip()
    return value if value else default


def prompt_password(prompt: str, min_len: int = 8) -> str:
    while True:
        pwd = getpass.getpass(f"{prompt}: ")
        if not pwd:
            print("[!] Password cannot be empty. Please try again.")
            continue
        if len(pwd) < min_len:
            print(f"[!] Password must be at least {min_len} characters long. Please try again.")
            continue
        confirm = getpass.getpass("Confirm password: ")
        if pwd != confirm:
            print("[!] Passwords do not match. Please try again.")
            continue
        return pwd


def generate_fernet_key() -> str:
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()
    except Exception:
        import base64
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def run_setup(force: bool = False):
    print("=" * 70)
    print("🚀 IntentLead AI - Interactive Setup & Configuration Wizard")
    print("=" * 70)
    print("This wizard will help you configure your own database, admin operator,")
    print("Gemini AI API, Telegram bot, and outreach mailboxes.")
    print("All credentials will be saved securely to your local, untracked .env file.")
    print("=" * 70 + "\n")

    root_env = WORKSPACE_ROOT / ".env"
    api_env = API_DIR / ".env"

    if (root_env.exists() or api_env.exists()) and not force:
        print("[!] An existing configuration (.env) was detected.")
        choice = input("Do you want to reconfigure and overwrite it? (y/N): ").strip().lower()
        if choice not in ("y", "yes"):
            print("\n[OK] Setup aborted. Your existing configuration and database were left untouched.")
            return

    # 1. Database Configuration
    print("\n--- [1/6] Database Configuration ---")
    print("Choose your database engine:")
    print("  [1] SQLite (Recommended - Zero Setup, Fast Single-File)")
    print("  [2] Docker Compose PostgreSQL (Runs via Docker on localhost:5432)")
    print("  [3] Custom PostgreSQL URL (Supabase, Neon, AWS RDS, etc.)")
    db_choice = prompt_input("Enter choice [1/2/3]", default="1")

    if db_choice == "2":
        db_user = prompt_input("PostgreSQL Username", default="intentlead")
        db_pass = prompt_input("PostgreSQL Password", default="password")
        db_host = prompt_input("PostgreSQL Host", default="localhost")
        db_port = prompt_input("PostgreSQL Port", default="5432")
        db_name = prompt_input("Database Name", default="intentlead")
        database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        print(f"[OK] Configured PostgreSQL: {database_url}")
        print("     Tip: Start the database container with: docker compose up -d db")
    elif db_choice == "3":
        database_url = prompt_input(
            "Enter PostgreSQL Connection URL (e.g. postgresql://user:pass@host:5432/dbname)"
        )
        while not database_url:
            print("[!] Connection URL cannot be empty.")
            database_url = prompt_input("Enter PostgreSQL Connection URL")
    else:
        database_url = "sqlite:///./intentlead.db"
        print("[OK] Selected SQLite: local file 'intentlead.db' will be used.")

    # 2. Web Admin Operator Account
    print("\n--- [2/6] Web Operator Account (Dashboard Login) ---")
    print("Create the master operator account for logging into the web dashboard.")
    admin_user = prompt_input("Admin Username", default="admin")
    admin_password = prompt_password("Admin Password (min 8 chars)", min_len=8)

    # 3. Agency Identity & Sender
    print("\n--- [3/6] Agency Identity & Email Branding ---")
    agency_name = prompt_input("Agency / Business Name", default="Acme Growth Labs")
    sender_name = prompt_input("Sender First Name (shown in emails)", default="Alex")
    sender_email = prompt_input("Default Sender Email", default="outreach@example.com")
    physical_address = prompt_input(
        "Agency Physical Address (CAN-SPAM compliance)",
        default="100 Innovation Way, Suite 400, Wilmington, DE 19801"
    )

    # 4. AI Intelligence (Google Gemini)
    print("\n--- [4/6] AI Intelligence & Google Gemini API ---")
    print("IntentLead uses Google Gemini to audit prospect websites and craft personalized emails.")
    print("You can get a free API key at: https://aistudio.google.com/")
    gemini_key = prompt_input("Google Gemini API Key (Enter to skip)", default="")
    gemini_model = prompt_input("Gemini Model", default="gemini-1.5-flash")

    # 5. Telegram Bot Automation
    print("\n--- [5/6] Telegram Bot Control Plane (Optional) ---")
    print("Control campaigns and review approvals directly from your phone.")
    print("1. Get a bot token from @BotFather on Telegram.")
    print("2. Get your numeric User ID from @userinfobot.")
    telegram_token = prompt_input("Telegram Bot Token (Enter to skip)", default="")
    telegram_user_id = ""
    if telegram_token:
        telegram_user_id = prompt_input("Your Numeric Telegram User ID", default="")

    # 6. Email Outreach & SMTP Settings
    print("\n--- [6/6] Email Outreach & Safety Settings ---")
    print("Outreach Mode:")
    print("  [1] Dry-Run Mode (Safe simulation - generates pitches but sends NO real emails)")
    print("  [2] Live Active Mode (Dispatches real outbound emails via SMTP)")
    mode_choice = prompt_input("Enter choice [1/2]", default="1")
    dry_run = "false" if mode_choice == "2" else "true"

    smtp_host = "smtp.gmail.com"
    smtp_port = "587"
    smtp_user = sender_email
    smtp_pass = ""

    configure_smtp = prompt_input("Configure Gmail / SMTP account now? (y/N)", default="N").lower()
    if configure_smtp in ("y", "yes"):
        print("\nNote for Gmail: Use a Google Account App Password, not your regular password.")
        smtp_host = prompt_input("SMTP Host", default="smtp.gmail.com")
        smtp_port = prompt_input("SMTP Port", default="587")
        smtp_user = prompt_input("SMTP User / Email", default=sender_email)
        smtp_pass = getpass.getpass("SMTP App Password: ").strip()

        add_pool = prompt_input("Also add this account to mailboxes.json pool? (Y/n)", default="Y").lower()
        if add_pool in ("y", "yes"):
            mailboxes_file = WORKSPACE_ROOT / "mailboxes.json"
            mailboxes = []
            if mailboxes_file.exists():
                try:
                    mailboxes = json.loads(mailboxes_file.read_text(encoding="utf-8"))
                    if not isinstance(mailboxes, list):
                        mailboxes = []
                except Exception:
                    mailboxes = []
            
            # Avoid duplicate
            if not any(m.get("email") == smtp_user for m in mailboxes):
                mailboxes.append({
                    "email": smtp_user,
                    "password": smtp_pass,
                    "sender_name": sender_name,
                    "daily_limit": 40,
                    "is_active": True
                })
                mailboxes_file.write_text(json.dumps(mailboxes, indent=2), encoding="utf-8")
                print(f"[OK] Added {smtp_user} to mailboxes.json pool.")

    # Generate Cryptographic Secrets
    unsubscribe_secret = secrets.token_hex(32)
    fernet_key = generate_fernet_key()
    webhook_secret = secrets.token_hex(16)

    # Build .env content
    env_content = f"""# ==============================================================================
# IntentLead AI - Environment Configuration
# Generated by Interactive Setup Wizard
# ==============================================================================

APP_ENV=development
LOG_LEVEL=INFO

# Database Connection URL
DATABASE_URL={database_url}

# Discovery Scraper Provider ("scrapling", "google_maps", "mock")
DISCOVERY_PROVIDER=scrapling

# Agency Identity & Default Branding
AGENCY_NAME={agency_name}
AGENCY_SENDER_NAME={sender_name}

# Outreach Safety Switch (Dry-run mode prevents accidental email dispatch)
OUTREACH_DRY_RUN={dry_run}

# Telegram Bot Automation
TELEGRAM_BOT_TOKEN={telegram_token}
TELEGRAM_ALLOWED_USER_ID={telegram_user_id}
TELEGRAM_WEBHOOK_SECRET={webhook_secret}

# API Security, CORS & Rate Limiting
API_KEY=
RATE_LIMIT_PER_MINUTE=60
CORS_ORIGINS=*

# Google Gemini / LLM API Key
USER_LLM_API_KEY={gemini_key}
USER_LLM_MODEL={gemini_model}
USER_LLM_BASE_URL=

# Email Dispatch Configuration
EMAIL_PROVIDER=smtp
SENDER_EMAIL={sender_email}

# Primary SMTP Settings
SMTP_HOST={smtp_host}
SMTP_PORT={smtp_port}
SMTP_USER={smtp_user}
SMTP_PASSWORD={smtp_pass}
SMTP_USE_TLS=true

# Multi-Mailbox Pool Configuration
MAILBOXES_FILE=mailboxes.json
MAX_EMAILS_PER_DAY=40
ENABLE_DISPATCH_PACING=true

# Compliance & Unsubscribe Settings
AGENCY_PHYSICAL_ADDRESS={physical_address}
UNSUBSCRIBE_BASE_URL=http://localhost:8000/unsubscribe
UNSUBSCRIBE_SECRET={unsubscribe_secret}

# Credential Encryption at Rest (Fernet authenticated encryption)
FIELD_ENCRYPTION_KEY={fernet_key}

# Webhook Verification Secrets
RESEND_WEBHOOK_SECRET=
OUTREACH_WEBHOOK_SECRET=
MAILGUN_WEBHOOK_SIGNING_KEY=
"""

    print("\nSaving configuration...")
    root_env.write_text(env_content, encoding="utf-8")
    api_env.write_text(env_content, encoding="utf-8")
    print(f"[OK] Saved .env configuration successfully.")

    # Initialize Database Schema & Admin Account
    print("\nInitializing database schema...")
    os.environ["DATABASE_URL"] = database_url
    os.environ["APP_ENV"] = "development"

    try:
        from app.db import ensure_schema, SessionLocal
        from app.models import OperatorUser, utc_now
        from app.services.auth import hash_password

        ensure_schema()
        print("[OK] Database tables created / verified.")

        with SessionLocal() as db:
            pwd_hash = hash_password(admin_password)
            user = db.query(OperatorUser).filter_by(username=admin_user).first()
            if user:
                user.password_hash = pwd_hash
                user.is_active = True
                db.commit()
                print(f"[OK] Updated operator '{admin_user}' in database.")
            else:
                user = OperatorUser(
                    username=admin_user,
                    password_hash=pwd_hash,
                    is_active=True,
                    created_at=utc_now(),
                )
                db.add(user)
                db.commit()
                print(f"[OK] Created operator '{admin_user}' in database.")
    except Exception as exc:
        print(f"[!] Note: Database schema initialization encountered: {exc}")
        print("    You can initialize the schema anytime by running: alembic upgrade head")

    print("\n" + "=" * 70)
    print("🎉 IntentLead AI Setup Complete!")
    print("=" * 70)
    print("To launch IntentLead AI:")
    print("  • Windows PowerShell:  .\\start.ps1 -Both")
    print("  • Linux / macOS:       ./start.sh --both")
    print("  • Docker Compose:      docker compose up -d")
    print()
    print("Access your instance:")
    print(f"  • Web Dashboard:  http://localhost:8000 (Login: {admin_user})")
    if telegram_token:
        print("  • Telegram Bot:   Open your bot and send /start or /findleads")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    force_mode = "--force" in sys.argv or "-f" in sys.argv
    run_setup(force=force_mode)
