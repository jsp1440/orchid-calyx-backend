from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

DATABASE_URL = os.getenv("CALYX_BRAIN_002_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="disposable PostgreSQL URL is required"
)


def _sql(name: str) -> str:
    return (Path(__file__).parents[1] / "migrations" / name).read_text(encoding="utf-8")


def test_reasoning_migration_apply_idempotent_and_rollback():
    assert DATABASE_URL
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(_sql("101_research_workspace_foundation.sql"))
        migration = _sql("103_reasoning_ledger.sql")
        connection.execute(migration)
        connection.execute(migration)
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'reasoning_ledger'
                """
            )
        }
        assert tables == {"ledger_heads", "ledger_revisions", "audit_events"}
        connection.execute(_sql("103_reasoning_ledger_rollback.sql"))
        remaining = connection.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name='reasoning_ledger'"
        ).fetchone()
        assert remaining is None
