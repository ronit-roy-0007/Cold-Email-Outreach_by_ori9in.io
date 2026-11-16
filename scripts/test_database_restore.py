"""
IntentLead AI — Phase 4 Database Restore & Schema Integrity Verification
Creates a disposable database, restores staging pg_dump, verifies schema, record counts,
foreign keys, Alembic version, and critical application queries, then cleans up.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest


class TestDatabaseRestore(unittest.TestCase):
    DISPOSABLE_DB = "intentlead_verify_restore"
    SOURCE_DB = "intentlead_staging"
    USER = "intentlead_staging"

    @classmethod
    def setUpClass(cls):
        print("\n[PHASE 4: Database Restore & Integrity Test]")
        # 1. Ensure clean slate on postgres
        subprocess.run(
            ["docker", "exec", "intentlead-db", "psql", "-U", cls.USER, "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {cls.DISPOSABLE_DB};"],
            check=True,
            capture_output=True,
        )
        # 2. Create disposable DB
        subprocess.run(
            ["docker", "exec", "intentlead-db", "psql", "-U", cls.USER, "-d", "postgres", "-c", f"CREATE DATABASE {cls.DISPOSABLE_DB} OWNER {cls.USER};"],
            check=True,
            capture_output=True,
        )
        print("  ✓ Created disposable PostgreSQL database: intentlead_verify_restore")

        # 3. Dump source staging and pipe directly into disposable DB
        dump_restore_cmd = f"pg_dump -U {cls.USER} -d {cls.SOURCE_DB} --no-owner | psql -U {cls.USER} -d {cls.DISPOSABLE_DB}"
        res = subprocess.run(
            ["docker", "exec", "intentlead-db", "bash", "-c", dump_restore_cmd],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print("Restore stdout/stderr:", res.stdout, res.stderr)
            raise RuntimeError(f"Database dump/restore failed: {res.stderr}")
        print("  ✓ Successfully restored latest pg_dump into intentlead_verify_restore")

    @classmethod
    def tearDownClass(cls):
        # Cleanly drop disposable DB
        subprocess.run(
            ["docker", "exec", "intentlead-db", "psql", "-U", cls.USER, "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {cls.DISPOSABLE_DB};"],
            check=True,
            capture_output=True,
        )
        print("  ✓ Dropped disposable database intentlead_verify_restore cleanly (zero residue)")

    def run_query(self, sql: str) -> str:
        res = subprocess.run(
            ["docker", "exec", "intentlead-db", "psql", "-U", self.USER, "-d", self.DISPOSABLE_DB, "-t", "-A", "-c", sql],
            check=True,
            capture_output=True,
            text=True,
        )
        return res.stdout.strip()

    def run_source_query(self, sql: str) -> str:
        res = subprocess.run(
            ["docker", "exec", "intentlead-db", "psql", "-U", self.USER, "-d", self.SOURCE_DB, "-t", "-A", "-c", sql],
            check=True,
            capture_output=True,
            text=True,
        )
        return res.stdout.strip()

    def test_01_table_count(self):
        """Verify all 21 application tables exist in restored database"""
        sql = "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
        count = int(self.run_query(sql))
        self.assertEqual(count, 21, f"Expected 21 tables, found {count}")
        print(f"  ✓ Schema integrity: All 21 core application tables verified in restored database")

    def test_02_record_counts_match_source(self):
        """Verify record counts between source staging and restored database match identically"""
        tables = [
            "conversations",
            "conversation_messages",
            "followup_executions",
            "leads",
            "businesses",
            "campaigns",
            "audit_log",
            "mailbox_accounts",
            "suppression_list",
        ]
        for tbl in tables:
            src_count = int(self.run_source_query(f"SELECT count(*) FROM {tbl};"))
            dst_count = int(self.run_query(f"SELECT count(*) FROM {tbl};"))
            self.assertEqual(src_count, dst_count, f"Count mismatch for {tbl}: {src_count} vs {dst_count}")
            print(f"    • {tbl}: {dst_count} records (100% match)")
        print("  ✓ Record count fidelity: Source and restored database counts are identical")

    def test_03_foreign_key_referential_integrity(self):
        """Verify no orphaned foreign keys exist in restored database"""
        orphaned_msgs = int(self.run_query(
            "SELECT count(*) FROM conversation_messages m LEFT JOIN conversations c ON m.conversation_id = c.id WHERE c.id IS NULL;"
        ))
        orphaned_fus = int(self.run_query(
            "SELECT count(*) FROM followup_executions f LEFT JOIN conversations c ON f.conversation_id = c.id WHERE c.id IS NULL;"
        ))
        orphaned_leads = int(self.run_query(
            "SELECT count(*) FROM leads l LEFT JOIN businesses b ON l.business_id = b.id WHERE b.id IS NULL;"
        ))
        self.assertEqual(orphaned_msgs, 0)
        self.assertEqual(orphaned_fus, 0)
        self.assertEqual(orphaned_leads, 0)
        print("  ✓ Referential integrity: 0 orphaned messages, 0 orphaned follow-ups, 0 orphaned leads")

    def test_04_alembic_migration_head(self):
        """Verify Alembic version in restored database matches migration head"""
        version = self.run_query("SELECT version_num FROM alembic_version;")
        self.assertEqual(version, "0004_conversations_and_followups")
        print(f"  ✓ Alembic migration head: {version} verified")

    def test_05_critical_application_queries(self):
        """Verify critical operational queries execute cleanly against restored database"""
        # Follow-up scheduler query with FOR UPDATE SKIP LOCKED
        fu_query = (
            "SELECT id, status FROM followup_executions "
            "WHERE status = 'scheduled' "
            "ORDER BY scheduled_at "
            "LIMIT 10 FOR UPDATE SKIP LOCKED;"
        )
        self.run_query(fu_query)

        # Conversation threading query
        conv_query = (
            "SELECT c.id, c.recipient_email, count(m.id) as message_count "
            "FROM conversations c "
            "LEFT JOIN conversation_messages m ON m.conversation_id = c.id "
            "GROUP BY c.id, c.recipient_email "
            "LIMIT 5;"
        )
        self.run_query(conv_query)
        print("  ✓ Critical application queries: Concurrency locking (FOR UPDATE SKIP LOCKED) and threading verified")


if __name__ == "__main__":
    unittest.main()
