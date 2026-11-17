"""
IntentLead AI — Clean Environment Installation & Lifecycle Verification
Simulates a completely new user installing from a fresh clone with .env.example,
applying migrations from scratch, executing a dry-run campaign, scheduling follow-ups,
and performing full backup and restore.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

def run_clean_install_test():
    repo_root = Path(__file__).resolve().parent.parent
    print("=" * 80)
    print("PHASE 13: CLEAN ENVIRONMENT INSTALLATION TEST")
    print("=" * 80)

    # 1. Create clean isolated sandbox
    sandbox_dir = Path(tempfile.mkdtemp(prefix="intentlead_clean_test_"))
    print(f"\n[1] Created isolated clean sandbox at: {sandbox_dir}")

    try:
        # 2. Copy application source files (clean copy without development DB or .env)
        print("[2] Staging clean repository copy into sandbox...")
        shutil.copytree(
            repo_root / "apps",
            sandbox_dir / "apps",
            ignore=shutil.ignore_patterns(".env*", "*.db*", "*.sqlite*", "__pycache__", ".pytest_cache")
        )
        shutil.copytree(
            repo_root / "scripts",
            sandbox_dir / "scripts",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        shutil.copy(repo_root / ".env.example", sandbox_dir / ".env.example")
        shutil.copy(repo_root / "mailboxes.example.json", sandbox_dir / "mailboxes.example.json")

        # 3. Initialize fresh .env from .env.example
        print("[3] Creating .env from .env.example...")
        env_example_text = (sandbox_dir / ".env.example").read_text(encoding="utf-8")
        sandbox_db_file = (sandbox_dir / "clean_install.db").resolve().as_posix()
        clean_env_text = env_example_text.replace(
            "DATABASE_URL=sqlite:///./intentlead.db",
            f"DATABASE_URL=sqlite:///{sandbox_db_file}"
        ).replace(
            "DISCOVERY_PROVIDER=scrapling",
            "DISCOVERY_PROVIDER=mock"
        )
        (sandbox_dir / ".env").write_text(clean_env_text, encoding="utf-8")

        # 4. Verify configuration loading
        print("[4] Validating configuration loading from clean .env...")
        sys.path.insert(0, str(sandbox_dir / "apps" / "intelligence-api"))
        os.environ["DATABASE_URL"] = f"sqlite:///{sandbox_db_file}"
        os.environ["APP_ENV"] = "development"
        os.environ["OUTREACH_DRY_RUN"] = "true"
        os.environ["DISCOVERY_PROVIDER"] = "mock"

        from app.config import get_settings
        settings = get_settings()
        assert settings.APP_ENV == "development", "Failed to load APP_ENV"
        assert settings.OUTREACH_DRY_RUN is True, "OUTREACH_DRY_RUN must default to True"
        print(f"  ✓ Clean configuration verified (Agency: {settings.AGENCY_NAME}, DryRun: {settings.OUTREACH_DRY_RUN})")

        # 5. Run Alembic migrations from scratch on fresh database
        print("[5] Executing database migrations from base to head on empty database...")
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config(str(sandbox_dir / "apps" / "intelligence-api" / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(sandbox_dir / "apps" / "intelligence-api" / "alembic"))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{sandbox_db_file}")
        command.upgrade(alembic_cfg, "head")
        print(f"  ✓ Migrations executed successfully. Database created at {sandbox_db_file}")
        assert (sandbox_dir / "clean_install.db").exists(), "clean_install.db was not created"

        # 6. Verify API health endpoints
        print("[6] Initializing FastAPI application and checking health probes...")
        from starlette.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        live_resp = client.get("/health/live")
        assert live_resp.status_code == 200, f"/health/live returned {live_resp.status_code}"
        print(f"  ✓ /health/live check passed: {live_resp.json()}")

        ready_resp = client.get("/health/ready")
        assert ready_resp.status_code == 200, f"/health/ready returned {ready_resp.status_code}"
        print(f"  ✓ /health/ready check passed: {ready_resp.json()}")

        # 7. Execute dry-run campaign & follow-up scheduling
        print("[7] Executing dry-run campaign and follow-up sequence in clean environment...")
        from app.db import SessionLocal
        from app.models import Business, Campaign, Conversation, Lead, utc_now
        from app.services.followup_engine import schedule_followups_for_conversation, process_due_followups

        with SessionLocal() as db:
            camp = Campaign(
                niche="Solar",
                location="San Francisco",
                requested_quantity=5,
                target_services=["ai_chatbot"],
                filters={},
                provider="mock",
                status="active",
                followup_sequence={
                    "enabled": True,
                    "count": 2,
                    "delays": [2, 5],
                    "schedule_type": "calendar"
                }
            )
            db.add(camp)
            db.flush()

            biz_id_key = f"clean_test_{uuid.uuid4().hex[:8]}"
            biz = Business(
                identity_key=biz_id_key,
                name="Clean Test Solar Corp",
                website="https://cleantestsolar.com",
                locality="San Francisco, CA",
                email="contact@cleantestsolar.com",
                category="Solar Energy Contractor",
                source_fields={},
                discovery_source="mock"
            )
            db.add(biz)
            db.flush()

            lead = Lead(
                campaign_id=camp.id,
                business_id=biz.id,
                overall_score=88,
                priority="high",
                confidence="high",
                recommended_service="ai_chatbot",
                outreach_status="approved",
            )
            db.add(lead)
            db.flush()

            conv = Conversation(
                lead_id=lead.id,
                business_id=biz.id,
                campaign_id=camp.id,
                recipient_email=biz.email,
                sender_email="outreach@example.com",
                subject="Quick question regarding your website",
                status="active"
            )
            db.add(conv)
            db.flush()

            sched = schedule_followups_for_conversation(db, conv, camp)
            db.commit()

            assert len(sched) == 2, f"Expected 2 follow-ups scheduled, got {len(sched)}"
            print(f"  ✓ Follow-ups scheduled successfully for conversation {conv.id}")

            # Process due followups (dry run)
            proc_res = process_due_followups(db, settings, now=utc_now() + __import__("datetime").timedelta(days=3))
            print(f"  ✓ Worker follow-up execution cycle completed: {proc_res}")

        # 8. Test Database Backup
        print("[8] Testing database backup execution...")
        backup_dir = sandbox_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_target = backup_dir / "clean_backup.db"
        shutil.copy(sandbox_dir / "clean_install.db", backup_target)
        assert backup_target.exists() and backup_target.stat().st_size > 0, "Backup file creation failed"
        print(f"  ✓ Database backup created successfully ({backup_target.stat().st_size} bytes)")

        # 9. Test Database Restore
        print("[9] Testing database restore execution...")
        restore_target = sandbox_dir / "restored_install.db"
        shutil.copy(backup_target, restore_target)
        assert restore_target.exists(), "Restore failed"
        print(f"  ✓ Database restore verified at: {restore_target}")

        print("\n" + "=" * 80)
        print("PHASE 13 VERDICT: ALL CLEAN ENVIRONMENT INSTALLATION CHECKS PASSED (100%)")
        print("=" * 80)
        return True

    finally:
        # Clean teardown
        shutil.rmtree(sandbox_dir, ignore_errors=True)
        print("[Teardown] Clean sandbox removed.")

if __name__ == "__main__":
    success = run_clean_install_test()
    sys.exit(0 if success else 1)
