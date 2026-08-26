"""Gate 1 diagnostic and migration safety (CALYX-RECOVERY-001 items 6 and 7).

Neither is applied or dispatched here. These are the static checks that make
it safe for an owner to do so.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "CALYX-RECOVERY-001-research-station-records.sql"
WORKFLOW = ROOT / ".github" / "workflows" / "calyx-recovery-001-gate1.yml"
SCRIPT = ROOT / "scripts" / "calyx_recovery_gate1.py"


# ------------------------------------------------------------- migration safety


def test_the_migration_is_idempotent_by_construction():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "CREATE SCHEMA IF NOT EXISTS" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql


def test_the_migration_destroys_nothing():
    """A recovery migration that can drop anything is not a recovery."""
    sql = MIGRATION.read_text(encoding="utf-8").upper()

    for destructive in ("DROP ", "TRUNCATE", "DELETE FROM", "ALTER COLUMN", "DROP COLUMN"):
        assert destructive not in sql, f"migration contains {destructive!r}"


def test_the_migration_creates_only_its_own_table():
    """It must not touch a relation another subsystem owns."""
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.count("CREATE TABLE") == 1
    assert "oc_admin.research_station_records" in sql


def test_the_primary_key_is_sufficient_for_idempotent_writes():
    """The store upserts on exactly this key."""
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "PRIMARY KEY (owner_key, project_id, kind, record_id)" in sql


def test_the_index_matches_the_cold_start_read():
    """manifest() lists one project's records of one kind on every cold read."""
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "(owner_key, project_id, kind)" in sql


def test_the_migration_table_matches_what_the_store_writes():
    from runtime.research_station_store import TABLE

    assert TABLE == "oc_admin.research_station_records"
    assert TABLE in MIGRATION.read_text(encoding="utf-8")


# ------------------------------------------------------------- workflow safety


def test_the_gate1_workflow_is_dispatch_only_and_read_only():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch" in text
    assert "contents: read" in text
    # No push/schedule trigger: this reads a production database and must run
    # only when somebody asks it to.
    assert "\n  push:" not in text
    assert "\n  schedule:" not in text


def test_the_gate1_workflow_has_real_steps():
    """A job with steps:null is not validation, and never was."""
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "steps:" in text
    assert "steps: null" not in text
    assert text.count("- name:") + text.count("- uses:") >= 4


def test_the_gate1_workflow_publishes_a_receipt():
    assert "upload-artifact" in WORKFLOW.read_text(encoding="utf-8")


# ------------------------------------------------------------ script behaviour


def test_the_diagnostic_performs_no_writes():
    """SELECT-only, asserted against the source rather than trusted."""
    source = SCRIPT.read_text(encoding="utf-8").upper()

    for mutation in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE TABLE", "ALTER "):
        assert mutation not in source, f"diagnostic contains {mutation!r}"


def test_the_diagnostic_never_prints_the_connection_string():
    source = SCRIPT.read_text(encoding="utf-8")

    # The URL is read once and passed to connect(); it is never formatted into
    # output, and the exception path reports only the exception class.
    assert 'f"{type(exc).__name__}"' in source
    assert "print(url" not in source
    assert '"database_url"' not in source


def test_without_a_database_every_field_is_unknown_not_zero(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
    )
    assert result.returncode == 0

    import json

    receipt = json.loads(result.stdout)
    fields = receipt["fields"]
    assert receipt["read_only"] is True
    assert fields["database_connectivity"]["state"] == "BLOCKED"
    # The distinction the whole receipt exists to preserve.
    assert fields["build051_research_requests"]["state"] == "UNKNOWN"
    assert "row_count" not in fields["build051_research_requests"]


def test_a_missing_relation_is_unknown_rather_than_degraded():
    """This script cannot tell "not deployed" from "named differently"."""
    sys.path.insert(0, str(ROOT))
    from scripts.calyx_recovery_gate1 import UNKNOWN, _classify

    assert _classify(True, False) == UNKNOWN
