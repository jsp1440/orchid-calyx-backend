from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.reasoning_ledger.models import (
    ConflictDispositionType,
    LedgerEntry,
    LedgerEntryKind,
)
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService

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


def test_postgres_conflict_dispositions_round_trip_history_and_audit():
    assert DATABASE_URL
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(_sql("101_research_workspace_foundation.sql"))
        connection.execute(_sql("103_reasoning_ledger.sql"))
        project_id = str(
            connection.execute(
                "INSERT INTO research_station.projects(owner_subject,title) "
                "VALUES('owner-a','Disposition PostgreSQL') RETURNING project_id"
            ).fetchone()[0]
        )
    sqlalchemy_url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(sqlalchemy_url)
    session_local = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        for state, expected in (
            ("resolved", ConflictDispositionType.RESOLVED),
            ("superseded", ConflictDispositionType.SUPERSEDED),
        ):
            with session_local() as db:
                service = OperationalReasoningLedgerService(db)
                ledger, _ = service.create(
                    owner="owner-a",
                    project_id=project_id,
                    title=f"PostgreSQL {state}",
                    description="",
                )
                ledger = service.append(
                    str(ledger.ledger_id),
                    LedgerEntry(
                        kind=LedgerEntryKind.CONFLICT,
                        text=f"PostgreSQL {state} conflict",
                        author="owner-a",
                        tenant_id="owner-a",
                        project_id=project_id,
                    ),
                    owner="owner-a",
                    expected_version=ledger.version,
                )
                conflict_id = ledger.entries[-1].entry_id
                ledger = service.resolve_conflict(
                    str(ledger.ledger_id),
                    conflict_id,
                    owner="owner-a",
                    expected_version=ledger.version,
                    resolution_state=state,
                    rationale=f"PostgreSQL {state} rationale",
                )
                ledger_id = str(ledger.ledger_id)
            with session_local() as db:
                service = OperationalReasoningLedgerService(db)
                current = service.current(ledger_id, "owner-a")
                disposition = current.conflict_dispositions[-1]
                assert disposition.disposition is expected
                assert disposition.rationale == f"PostgreSQL {state} rationale"
                assert disposition.actor == "owner-a"
                assert disposition.conflict_entry_id == conflict_id
                history = service.history(ledger_id, "owner-a")
                assert history["revisions"][-2].conflict_dispositions == ()
                assert history["revisions"][-1].conflict_dispositions == (disposition,)
                assert history["audit_events"][-1]["event_type"] == (
                    "CONFLICT_RESOLVED"
                    if state == "resolved"
                    else "CONFLICT_SUPERSEDED"
                )
    finally:
        engine.dispose()
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(_sql("103_reasoning_ledger_rollback.sql"))
