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
