#!/usr/bin/env python3
"""
IntentLead AI — Operator Account Bootstrap CLI
Enables system administrators to provision or reset operator credentials.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

# Ensure intelligence-api is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "intelligence-api")))

from app.config import get_settings
from app.db import SessionLocal
from app.models import OperatorUser, utc_now
from app.services.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description="Bootstrap or reset IntentLead AI operator account")
    parser.add_argument("--username", "-u", default="admin", help="Operator username (default: admin)")
    parser.add_argument("--password", "-p", help="Operator password (if omitted, interactive prompt is used)")
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        print("Error: Username cannot be empty.", file=sys.stderr)
        sys.exit(1)

    password = args.password
    if not password:
        password = getpass.getpass(f"Enter password for operator '{username}': ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    if len(password) < 8:
        print("Error: Password must be at least 8 characters long.", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    with SessionLocal() as db:
        user = db.query(OperatorUser).filter_by(username=username).first()
        pwd_hash = hash_password(password)
        if user:
            user.password_hash = pwd_hash
            user.is_active = True
            user.last_login_at = None
            db.commit()
            print(f"Success: Password for existing operator '{username}' has been updated.")
        else:
            user = OperatorUser(
                username=username,
                password_hash=pwd_hash,
                is_active=True,
                created_at=utc_now(),
            )
            db.add(user)
            db.commit()
            print(f"Success: New operator account '{username}' created successfully.")


if __name__ == "__main__":
    main()
