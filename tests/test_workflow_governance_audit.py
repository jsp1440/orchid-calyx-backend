from pathlib import Path

from scripts.audit_workflow_governance import classify


def test_manual_only_routine_workflow_is_owner_bottleneck(tmp_path: Path) -> None:
    path = tmp_path / "routine.yml"
    path.write_text(
        "name: Routine task\non:\n  workflow_dispatch:\njobs:\n  run:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "OWNER_BOTTLENECK"


def test_push_plus_manual_is_automatic_with_recovery(tmp_path: Path) -> None:
    path = tmp_path / "automatic.yml"
    path.write_text(
        "name: Automatic task\non:\n  push:\n    branches: [main]\n  workflow_dispatch:\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "AUTOMATIC_WITH_RECOVERY"
    assert finding.triggers == ["push", "workflow_dispatch"]


def test_confirmed_production_manual_workflow_is_destructive_gated(tmp_path: Path) -> None:
    path = tmp_path / "destructive.yml"
    path.write_text(
        "name: Destructive task\non:\n  workflow_dispatch:\n    inputs:\n      confirmation:\n        required: true\njobs:\n  apply:\n    environment: production\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "DESTRUCTIVE_GATED"


def test_production_migration_switch_is_destructive_gated(tmp_path: Path) -> None:
    path = tmp_path / "migration.yml"
    path.write_text(
        "name: Production migration\non:\n  workflow_dispatch:\n    inputs:\n      apply_migration:\n        required: true\n        type: boolean\njobs:\n  migrate:\n    environment: production\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "DESTRUCTIVE_GATED"
    assert finding.requires_confirmation is True
