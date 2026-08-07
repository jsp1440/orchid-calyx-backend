from __future__ import annotations

import json
from pathlib import Path

from scripts import activate_reasoning_publication_schemas as activation

ROOT = Path(__file__).parents[1]


def test_migration_identities_are_pinned_to_reviewed_files():
    report = activation.migration_identity_report()
    assert list(report) == [
        "103_reasoning_ledger.sql",
        "105_reasoning_ledger_publication_adapter.sql",
    ]
    assert all(item["matches"] for item in report.values())
    assert all(len(item["sha256"]) == 64 for item in report.values())


def test_schema_contract_includes_publication_snapshot_and_runtime_guards():
    assert "snapshot" in activation.REQUIRED_COLUMNS[
        "reasoning_publication.publication_artifacts"
    ]
    assert "reasoning_publication.protect_published_artifact" in activation.REQUIRED_FUNCTIONS
    assert "reasoning_publication.reject_attempt_mutation" in activation.REQUIRED_FUNCTIONS
    assert (
        "reasoning_publication.publication_artifacts.protect_reasoning_publication_identity"
        in activation.REQUIRED_TRIGGERS
    )
    assert (
        "reasoning_publication.publication_attempts.protect_reasoning_publication_attempt"
        in activation.REQUIRED_TRIGGERS
    )
    assert "idx_reasoning_publication_scope" in activation.REQUIRED_INDEXES


def test_missing_database_url_fails_closed_without_mutation(monkeypatch, tmp_path):
    evidence = tmp_path / "receipt.json"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CALYX_REASONING_MIGRATION_CONFIRM", raising=False)
    monkeypatch.setattr(activation, "EVIDENCE_PATH", evidence)

    assert activation.run(apply_requested=False) == 2
    report = json.loads(evidence.read_text())
    assert report["status"] == "blocked"
    assert "DATABASE_URL_MISSING" in report["blockers"]
    assert report["production_database_mutation_authorized"] is False
    assert report["production_database_mutation_attempted"] is False
    assert report["production_database_mutation_observed"] is False
    assert report["publication_authorized"] is False
    assert report["knowledge_graph_mutation_authorized"] is False


def test_apply_requires_separate_explicit_confirmation(monkeypatch, tmp_path):
    evidence = tmp_path / "receipt.json"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CALYX_REASONING_MIGRATION_CONFIRM", raising=False)
    monkeypatch.setattr(activation, "EVIDENCE_PATH", evidence)

    assert activation.run(apply_requested=True) == 2
    report = json.loads(evidence.read_text())
    assert report["apply_requested"] is True
    assert report["explicit_confirmation_present"] is False
    assert report["production_database_mutation_authorized"] is False
    assert report["production_database_mutation_attempted"] is False


def test_apply_migrations_records_completed_work_before_later_failure(monkeypatch, tmp_path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    first = migrations_dir / "103_reasoning_ledger.sql"
    second = migrations_dir / "105_reasoning_ledger_publication_adapter.sql"
    first.write_text("SELECT 103;", encoding="utf-8")
    second.write_text("SELECT 105;", encoding="utf-8")
    monkeypatch.setattr(activation, "ROOT", tmp_path)
    monkeypatch.setattr(
        activation,
        "MIGRATIONS",
        ((first.name, "unused"), (second.name, "unused")),
    )

    class ExpectedFailure(Exception):
        pass

    class Connection:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.rollback_called = False

        def execute(self, sql: str) -> None:
            self.calls.append(sql)
            if "105" in sql:
                raise ExpectedFailure("second migration failed")

        def rollback(self) -> None:
            self.rollback_called = True

    connection = Connection()
    results, failed = activation._apply_migrations(
        connection, error_type=ExpectedFailure
    )

    assert failed == second.name
    assert results == [
        {"filename": first.name, "started": True, "completed": True},
        {
            "filename": second.name,
            "started": True,
            "completed": False,
            "error_type": "ExpectedFailure",
        },
    ]
    assert connection.rollback_called is True


def test_production_workflow_is_manual_protected_and_defaults_read_only():
    workflow = (
        ROOT / ".github/workflows/calyx-reasoning-schema-production-activation.yml"
    ).read_text()
    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "apply_migrations:" in workflow
    assert "default: false" in workflow
    assert "pull_request:" not in workflow
    assert "CALYX_REASONING_MIGRATION_CONFIRM=APPLY_103_105" in workflow
    assert "discover_eligible_reasoning_ledgers.py" in workflow
    assert "run_supervised_reasoning_publication.py" not in workflow
