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


def test_required_boolean_input_production_manual_is_destructive_gated(tmp_path: Path) -> None:
    """build-051 pattern: manual-only, production env, required boolean input — no keyword phrase."""
    path = tmp_path / "build_051.yml"
    path.write_text(
        "name: BUILD-051 Production Activation\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      apply_migration:\n"
        "        description: Apply migration\n"
        "        required: true\n"
        "        default: false\n"
        "        type: boolean\n"
        "jobs:\n"
        "  migrate:\n"
        "    runs-on: ubuntu-latest\n"
        "    environment: production\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "DESTRUCTIVE_GATED"
    assert finding.requires_confirmation is True


def test_dispatch_gated_production_job_is_production_gated(tmp_path: Path) -> None:
    """Workflows where automatic trigger covers only validation but production job is dispatch-only."""
    path = tmp_path / "supervised.yml"
    path.write_text(
        "name: Supervised Demo\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "  pull_request:\n"
        "    paths:\n"
        "      - scripts/demo.py\n"
        "jobs:\n"
        "  validate:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo validate\n"
        "  publish:\n"
        "    if: github.event_name == 'workflow_dispatch'\n"
        "    runs-on: ubuntu-latest\n"
        "    environment: production\n"
        "    steps:\n"
        "      - run: echo publish\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "PRODUCTION_GATED"


def test_automatic_with_recovery_no_production_guard(tmp_path: Path) -> None:
    """Workflow with auto trigger + dispatch but no dispatch-gated production env remains AUTOMATIC_WITH_RECOVERY."""
    path = tmp_path / "recovery.yml"
    path.write_text(
        "name: CI with recovery\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo test\n",
        encoding="utf-8",
    )
    finding = classify(path, path.read_text(encoding="utf-8"))
    assert finding.classification == "AUTOMATIC_WITH_RECOVERY"
