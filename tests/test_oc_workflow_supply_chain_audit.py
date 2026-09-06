from __future__ import annotations

from pathlib import Path

from scripts.oc_workflow_supply_chain_audit import (
    audit_exit_code,
    audit_repository,
    classify_action,
    remediation_manifest,
)


def _write_workflow(root: Path, body: str) -> None:
    workflow = root / ".github" / "workflows" / "test.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(body, encoding="utf-8")


def test_classifies_local_first_party_and_third_party() -> None:
    assert classify_action("./.github/actions/local") == "local"
    assert classify_action("actions/checkout") == "first_party"
    assert classify_action("vendor/action") == "third_party"


def test_inventory_records_file_line_action_and_ref(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "name: test\nsteps:\n  - uses: actions/checkout@v4\n"
        "  - uses: vendor/action@0123456789abcdef0123456789abcdef01234567\n",
    )

    audit = audit_repository("backend", tmp_path)

    assert audit.state == "AVAILABLE"
    assert audit.mutable_count == 1
    assert audit.references[0].workflow_file == ".github/workflows/test.yml"
    assert audit.references[0].line == 3
    assert audit.references[0].action == "actions/checkout"
    assert audit.references[0].ref == "v4"
    assert audit.references[0].immutable is False
    assert audit.references[1].immutable is True


def test_yaml_valid_spacing_around_uses_colon_is_detected(tmp_path: Path) -> None:
    _write_workflow(tmp_path, "steps:\n  - uses : vendor/action@v1\n")

    audit = audit_repository("backend", tmp_path)

    assert audit.state == "AVAILABLE"
    assert audit.mutable_count == 1
    assert len(audit.references) == 1
    assert audit.references[0].action == "vendor/action"
    assert audit.references[0].ref == "v1"
    assert audit_exit_code((audit,)) == 1


def test_local_actions_are_excluded_from_remote_inventory(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "steps:\n  - uses: ./.github/actions/local@ignored\n"
        "  - uses: actions/setup-python@0123456789abcdef0123456789abcdef01234567\n",
    )

    audit = audit_repository("backend", tmp_path)

    assert len(audit.references) == 1
    assert audit.references[0].action == "actions/setup-python"


def test_missing_repository_is_explicit_unknown(tmp_path: Path) -> None:
    audit = audit_repository("frontend", tmp_path / "not-mounted")

    assert audit.state == "UNKNOWN"
    assert audit.mutable_count is None
    assert audit.references == ()


def test_remediation_manifest_lists_mutable_refs_without_rewriting(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    _write_workflow(backend, "steps:\n  - uses: actions/checkout@v4\n")
    _write_workflow(
        frontend,
        "steps:\n  - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n",
    )

    manifest = remediation_manifest(
        (
            audit_repository("backend", backend),
            audit_repository("frontend", frontend),
        )
    )

    assert manifest["schema_version"] == "oc.workflow-supply-chain-audit.v1"
    assert manifest["remediation_state"] == "REVIEW_REQUIRED"
    assert manifest["workflow_rewrites_performed"] is False
    mutable = manifest["mutable_remote_references"]
    assert isinstance(mutable, list)
    assert len(mutable) == 1
    assert mutable[0]["action"] == "actions/checkout"
    assert mutable[0]["ref"] == "v4"


def test_unknown_repository_fails_closed_in_manifest_and_exit(tmp_path: Path) -> None:
    unknown = audit_repository("frontend", tmp_path / "not-mounted")

    manifest = remediation_manifest((unknown,))

    assert manifest["remediation_state"] == "UNKNOWN"
    assert audit_exit_code((unknown,)) == 1


def test_clean_available_repository_exits_successfully(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "steps:\n  - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n",
    )
    clean = audit_repository("backend", tmp_path)

    assert remediation_manifest((clean,))["remediation_state"] == "NO_MUTABLE_REFS_FOUND"
    assert audit_exit_code((clean,)) == 0
