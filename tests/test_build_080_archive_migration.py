from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

DATABASE_URL = os.getenv("BUILD_080_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="BUILD_080_TEST_DATABASE_URL is not configured")
def test_archive_migration_is_additive_and_idempotent():
    migration = Path("migrations/106_institutional_archive_manager.sql").read_text(encoding="utf-8")
    rollback = Path("migrations/106_institutional_archive_manager_rollback.sql").read_text(encoding="utf-8")
    expected = {
        "archive_documents", "archive_files", "archive_entities", "archive_relationships",
        "archive_import_runs", "archive_provenance", "archive_checkpoints",
    }
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(migration)
        conn.execute(migration)
        rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'archive_%'").fetchall()
        assert {row[0] for row in rows} == expected
        conn.execute(rollback)
        remaining = conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'archive_%'").fetchone()[0]
        assert remaining == 0
        conn.rollback()
