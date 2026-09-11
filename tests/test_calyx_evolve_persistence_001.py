"""CALYX-EVOLVE-001 durable-persistence and migration contract tests.

CI has no PostgreSQL, so these tests check the two things that can be checked
without one and that break silently when they drift:

* the SQL the Postgres backend emits — which tables it touches, that every value
  is bound as a parameter rather than interpolated, and that the runs insert
  really is keyed on ``replay_key``;
* that the forward migration and its rollback agree with the table and column
  names the backend uses.

The loop itself was additionally exercised against a live PostgreSQL 16
instance during development; that is recorded in the pull request rather than
asserted here.
"""

from __future__ import annotations

import pathlib
import re

from runtime.calyx_evolve.campaign import CampaignRunner
from runtime.calyx_evolve.defaults import (
    DEFAULT_CAMPAIGN_ID,
    default_campaign,
    default_candidates,
    default_cognition,
)
from runtime.calyx_evolve.memory import (
    PERSISTENCE_MEMORY,
    PERSISTENCE_POSTGRES,
    InMemoryExperimentMemory,
    PostgresExperimentMemory,
    build_experiment_memory,
    persistence_mode,
)

MIGRATION = pathlib.Path("migrations/CALYX-EVOLVE-001-experiment-ledger.sql")
ROLLBACK = pathlib.Path("migrations/CALYX-EVOLVE-001-experiment-ledger_rollback.sql")

EXPECTED_TABLES = {
    "oc_admin.calyx_evolve_campaigns",
    "oc_admin.calyx_evolve_cognition_items",
    "oc_admin.calyx_evolve_candidates",
    "oc_admin.calyx_evolve_runs",
    "oc_admin.calyx_evolve_metrics",
    "oc_admin.calyx_evolve_findings",
    "oc_admin.calyx_evolve_promotion_proposals",
}


class RecordingCursor:
    """A cursor that records statements and returns nothing, like an empty table."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append((sql, tuple(params)))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def recording_execute(cursor: RecordingCursor):
    def _execute(callback):
        return callback(cursor)

    return _execute


def test_postgres_backend_touches_only_the_evolve_ledger():
    cursor = RecordingCursor()
    memory = PostgresExperimentMemory(execute=recording_execute(cursor))
    runner = CampaignRunner(memory=memory)

    runner.cycle(default_campaign(), default_cognition(), default_candidates())

    assert cursor.statements, "the Postgres backend issued no statements"
    referenced = set()
    for sql, _ in cursor.statements:
        referenced.update(re.findall(r"oc_admin\.[a-z_]+", sql))
    assert referenced <= EXPECTED_TABLES
    assert referenced == EXPECTED_TABLES


def test_postgres_backend_binds_every_value_as_a_parameter():
    cursor = RecordingCursor()
    memory = PostgresExperimentMemory(execute=recording_execute(cursor))
    CampaignRunner(memory=memory).cycle(
        default_campaign(), default_cognition(), default_candidates()
    )

    for sql, params in cursor.statements:
        # No caller-supplied identifier is ever interpolated into the statement.
        assert DEFAULT_CAMPAIGN_ID not in sql
        for candidate in default_candidates():
            assert candidate.candidate_id not in sql
        placeholders = sql.count("%s")
        assert placeholders == len(params), sql
        assert ";" not in sql.strip().rstrip(";")


def test_runs_insert_is_keyed_on_the_replay_key():
    cursor = RecordingCursor()
    memory = PostgresExperimentMemory(execute=recording_execute(cursor))
    CampaignRunner(memory=memory).cycle(
        default_campaign(), default_cognition(), default_candidates()
    )

    run_inserts = [
        sql
        for sql, _ in cursor.statements
        if "INSERT INTO oc_admin.calyx_evolve_runs" in sql
    ]
    assert run_inserts
    for sql in run_inserts:
        # Idempotency lives in the constraint, not in application luck.
        assert "ON CONFLICT (replay_key) DO NOTHING" in sql

    proposal_inserts = [
        sql
        for sql, _ in cursor.statements
        if "INSERT INTO oc_admin.calyx_evolve_promotion_proposals" in sql
    ]
    assert proposal_inserts
    for sql in proposal_inserts:
        assert "ON CONFLICT (proposal_id) DO UPDATE" in sql


def test_migration_creates_every_table_the_backend_uses():
    sql = MIGRATION.read_text()
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (oc_admin\.[a-z_]+)", sql))
    assert created == EXPECTED_TABLES

    # Every statement is idempotent, so the migration can be re-applied safely.
    assert sql.count("CREATE TABLE ") == sql.count("CREATE TABLE IF NOT EXISTS ")
    assert sql.count("CREATE INDEX ") == sql.count("CREATE INDEX IF NOT EXISTS ")
    assert sql.count("CREATE UNIQUE INDEX ") == sql.count(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
    )
    assert "DROP " not in sql
    assert "ALTER TABLE" not in sql

    # The idempotency and governance constraints are in the schema, not only in code.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS calyx_evolve_runs_replay_key_idx" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS calyx_evolve_candidates_novelty_idx" in sql
    assert "CHECK (state IN ('review_pending', 'blocked'))" in sql


def test_rollback_drops_exactly_what_the_migration_created():
    forward = set(
        re.findall(
            r"CREATE TABLE IF NOT EXISTS (oc_admin\.[a-z_]+)", MIGRATION.read_text()
        )
    )
    rollback_sql = ROLLBACK.read_text()
    dropped = set(re.findall(r"DROP TABLE IF EXISTS (oc_admin\.[a-z_]+)", rollback_sql))
    assert dropped == forward
    # The shared schema is not dropped: other BUILD migrations own tables in it.
    assert "DROP SCHEMA" not in rollback_sql


def test_persistence_mode_reports_the_configured_backend(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert persistence_mode() == PERSISTENCE_MEMORY
    assert isinstance(build_experiment_memory(), InMemoryExperimentMemory)

    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    assert persistence_mode() == PERSISTENCE_POSTGRES
    memory = build_experiment_memory(execute=recording_execute(RecordingCursor()))
    assert isinstance(memory, PostgresExperimentMemory)


def test_cognition_rows_are_insert_only():
    cursor = RecordingCursor()
    memory = PostgresExperimentMemory(execute=recording_execute(cursor))
    memory.record_cognition(DEFAULT_CAMPAIGN_ID, [item.to_dict() for item in default_cognition()])

    statements = [sql for sql, _ in cursor.statements]
    assert statements
    for sql in statements:
        assert "INSERT INTO oc_admin.calyx_evolve_cognition_items" in sql
        # A cognition item is immutable: a changed input is a new content hash.
        assert "DO NOTHING" in sql
        assert "DO UPDATE" not in sql
