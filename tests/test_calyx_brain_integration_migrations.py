from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

DATABASE_URL = os.getenv("CALYX_BRAIN_INTEGRATION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="disposable PostgreSQL 16 URL is required"
)
ROOT = Path(__file__).resolve().parents[1]


def _sql(name: str) -> str:
    return (ROOT / "migrations" / name).read_text(encoding="utf-8")


def _tables(connection, schema: str) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s
            """,
            (schema,),
        )
    }


def test_migrations_101_103_104_apply_in_order_idempotently_and_roll_back():
    assert DATABASE_URL
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(_sql("101_research_workspace_foundation.sql"))
        migration_103 = _sql("103_reasoning_ledger.sql")
        connection.execute(migration_103)
        connection.execute(migration_103)
        migration_104 = _sql("104_orchid_continuum_brain.sql")
        connection.execute(migration_104)
        connection.execute(migration_104)

        assert _tables(connection, "reasoning_ledger") == {
            "ledger_heads",
            "ledger_revisions",
            "audit_events",
        }
        assert _tables(connection, "oc_brain") == {
            "connector_registrations",
            "outreach_nodes",
            "outreach_edges",
        }
        assert "projects" in _tables(connection, "research_station")

        connection.execute(_sql("104_orchid_continuum_brain_rollback.sql"))
        assert _tables(connection, "oc_brain") == set()
        assert _tables(connection, "reasoning_ledger")
        connection.execute(_sql("103_reasoning_ledger_rollback.sql"))
        assert _tables(connection, "reasoning_ledger") == set()
        assert "projects" in _tables(connection, "research_station")
