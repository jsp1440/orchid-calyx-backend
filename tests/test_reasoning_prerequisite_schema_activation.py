from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts/activate_reasoning_prerequisite_schemas.py"
SPEC = importlib.util.spec_from_file_location(
    "reasoning_prereq_activation", SCRIPT_PATH
)
assert SPEC and SPEC.loader
activation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activation)


def _contract(*, complete: bool = False, safe_resume: bool = True, blockers=None):
    return {
        "complete": complete,
        "safe_resume": safe_resume,
        "blockers": [] if blockers is None else blockers,
    }


def test_migration_identities_match_repository_blobs():
    report = activation.migration_identity_report()
    assert set(report) == {name for name, _ in activation.MIGRATIONS}
    assert all(item["matches"] for item in report.values())
    assert all(len(item["sha256"]) == 64 for item in report.values())


def test_classification_fails_closed_on_identity_drift():
    result = activation.classify_preflight(_contract(), identities_match=False)
    assert result["status"] == "blocked"
    assert result["ready_to_apply"] is False
    assert "MIGRATION_IDENTITY_DRIFT" in result["blockers"]


def test_classification_accepts_safe_resumable_prefix():
    result = activation.classify_preflight(_contract(), identities_match=True)
    assert result == {
        "status": "ready",
        "activation_required": True,
        "ready_to_apply": True,
        "blockers": [],
    }


def test_classification_blocks_malformed_or_out_of_order_schema():
    result = activation.classify_preflight(
        _contract(
            safe_resume=False, blockers=["MALFORMED_PARTIAL_PREREQUISITE_SCHEMA"]
        ),
        identities_match=True,
    )
    assert result["status"] == "blocked"
    assert result["ready_to_apply"] is False


def test_classification_reports_complete_without_reapply():
    result = activation.classify_preflight(
        _contract(complete=True), identities_match=True
    )
    assert result == {
        "status": "passed",
        "activation_required": False,
        "ready_to_apply": False,
        "blockers": [],
    }


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_preflight_apply_and_idempotent_reapply(monkeypatch, tmp_path: Path):
    import psycopg

    dsn = os.environ["TEST_DATABASE_URL"]
    evidence = tmp_path / "receipt.json"
    monkeypatch.setattr(activation, "EVIDENCE_PATH", evidence)

    with psycopg.connect(dsn, autocommit=True) as connection:
        before = activation.inspect_contract(connection)
        assert before["complete"] is False
        assert before["safe_resume"] is True
        assert activation.classify_preflight(before, True)["ready_to_apply"] is True

        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.setenv("CALYX_REASONING_PREREQ_CONFIRM", activation.CONFIRMATION)
        monkeypatch.setattr("sys.argv", [str(SCRIPT_PATH), "--apply"])
        assert activation.main() == 0

        after = activation.inspect_contract(connection)
        assert after["complete"] is True
        assert after["blockers"] == []
        assert connection.execute(
            "SELECT to_regclass('reasoning_ledger.ledger_heads'), "
            "to_regclass('reasoning_publication.publication_artifacts')"
        ).fetchone() == (None, None)

        # A second explicit application is unnecessary; direct DDL replay proves
        # all five prerequisite migrations remain idempotent on the disposable DB.
        for filename, _ in activation.MIGRATIONS:
            connection.execute((ROOT / "migrations" / filename).read_text())
        replay = activation.inspect_contract(connection)
        assert replay["complete"] is True
        assert connection.execute(
            "SELECT to_regclass('reasoning_ledger.ledger_heads'), "
            "to_regclass('reasoning_publication.publication_artifacts')"
        ).fetchone() == (None, None)


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_malformed_partial_table_fails_closed():
    import psycopg

    dsn = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(dsn) as connection:
        # Simulate a damaged pre-existing prerequisite without permanently
        # contaminating the shared disposable service used by later CLI checks.
        connection.execute("DROP SCHEMA IF EXISTS research_station CASCADE")
        connection.execute("CREATE SCHEMA research_station")
        connection.execute(
            "CREATE TABLE research_station.projects (project_id uuid PRIMARY KEY)"
        )
        report = activation.inspect_contract(connection)
        assert report["malformed_partial_schema"] is True
        assert report["safe_resume"] is False
        result = activation.classify_preflight(report, identities_match=True)
        assert result["status"] == "blocked"
        assert "MALFORMED_PARTIAL_PREREQUISITE_SCHEMA" in result["blockers"]
        connection.rollback()
