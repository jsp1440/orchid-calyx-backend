from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_provider_free_worker",
    ROOT / "scripts" / "oc_swarm_provider_free_worker.py",
)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def issue(body: str, *, state: str = "OPEN") -> dict:
    return {"number": 1085, "state": state, "body": body}


def lease(writes: list[str] | None = None) -> str:
    writes = writes or []
    return (
        '[OC-SWARM-V4] Dependency/resource lease claimed: `'
        f'{{"reads":[],"writes":{writes!r}}}'.replace("'", '"')
        + "`."
    )


def test_explicit_provider_free_reconcile_produces_safe_receipt():
    result = worker.build_receipt(
        issue("OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: owner-gate"),
        lease_comment=lease(),
        changed_files=[],
        integration_sha="abc123",
    )
    assert result["disposition"] == "owner-gate"
    assert result["write_set"]["passed"] is True
    assert result["safety"] == {
        "provider_calls": False,
        "repository_writes": False,
        "merge_to_main": False,
        "production_deploy": False,
        "scientific_mutation": False,
        "sensitive_locality_access": False,
    }


def test_missing_mode_fails_closed():
    try:
        worker.build_receipt(
            issue("OC-SWARM-DISPOSITION: done"),
            lease_comment=lease(),
            changed_files=[],
            integration_sha="abc123",
        )
    except ValueError as exc:
        assert "marker missing" in str(exc)
    else:
        raise AssertionError("missing provider-free mode was accepted")


def test_unknown_disposition_fails_closed():
    try:
        worker.build_receipt(
            issue("OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: publish"),
            lease_comment=lease(),
            changed_files=[],
            integration_sha="abc123",
        )
    except ValueError as exc:
        assert "not fail-closed" in str(exc)
    else:
        raise AssertionError("unsafe disposition was accepted")


def test_actual_write_set_still_fails_closed():
    try:
        worker.build_receipt(
            issue("OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"),
            lease_comment=lease(),
            changed_files=["app/main.py"],
            integration_sha="abc123",
        )
    except ValueError as exc:
        assert "write set" in str(exc)
    else:
        raise AssertionError("undeclared repository write was accepted")


VALIDATION_EVIDENCE = {
    "schema": "oc.provider-free-validation-evidence.v1",
    "passed": True,
    "command_count": 1,
    "failed_command_ids": [],
    "results": [{"command_id": "control-plane-tests", "passed": True, "exit_code": 0}],
}

VALIDATE_BODY = (
    "OC-SWARM-PROVIDER-FREE: validate\n"
    "OC-SWARM-VALIDATE: control-plane-tests\n"
    "OC-SWARM-DISPOSITION: done"
)


def _validate(evidence, body: str = VALIDATE_BODY):
    return worker.build_receipt(
        issue(body),
        lease_comment=lease(),
        changed_files=[],
        integration_sha="abc123",
        validation=evidence,
    )


def test_validate_mode_carries_the_evidence_it_settled_on():
    receipt = _validate(VALIDATION_EVIDENCE)
    assert receipt["mode"] == "validate"
    assert receipt["disposition"] == "done"
    assert receipt["declared_commands"] == ["control-plane-tests"]
    assert receipt["validation"]["results"][0]["command_id"] == "control-plane-tests"


def test_a_failed_validation_settles_blocked_whatever_the_issue_declared():
    """An issue may declare what success would mean, never that it happened."""
    failed = dict(VALIDATION_EVIDENCE, passed=False, failed_command_ids=["control-plane-tests"])
    assert _validate(failed)["disposition"] == "blocked"


def test_missing_validation_evidence_is_refused():
    try:
        _validate(None)
    except ValueError as exc:
        assert "requires validation evidence" in str(exc)
    else:
        raise AssertionError("validate mode settled without evidence")


def test_evidence_for_other_commands_is_refused():
    # Evidence from a different run must not settle this task.
    mismatched = dict(
        VALIDATION_EVIDENCE,
        results=[{"command_id": "control-plane-compiles", "passed": True}],
    )
    try:
        _validate(mismatched)
    except ValueError as exc:
        assert "does not cover the declared commands" in str(exc)
    else:
        raise AssertionError("mismatched validation evidence was accepted")


def test_validate_mode_without_a_declared_command_is_refused():
    body = "OC-SWARM-PROVIDER-FREE: validate\nOC-SWARM-DISPOSITION: done"
    try:
        _validate(VALIDATION_EVIDENCE, body)
    except ValueError as exc:
        assert "declares no OC-SWARM-VALIDATE" in str(exc)
    else:
        raise AssertionError("a validation task validating nothing was accepted")


def test_reconcile_mode_may_not_smuggle_validation_evidence():
    try:
        worker.build_receipt(
            issue("OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"),
            lease_comment=lease(),
            changed_files=[],
            integration_sha="abc123",
            validation=VALIDATION_EVIDENCE,
        )
    except ValueError as exc:
        assert "does not run validation commands" in str(exc)
    else:
        raise AssertionError("reconcile accepted validation evidence it never produced")


def test_declared_commands_are_read_in_declared_order():
    body = (
        "OC-SWARM-PROVIDER-FREE: validate\n"
        "OC-SWARM-VALIDATE: provider-routing-tests\n"
        "OC-SWARM-VALIDATE: control-plane-tests\n"
        "OC-SWARM-DISPOSITION: done"
    )
    assert worker.declared_validation_commands(body) == [
        "provider-routing-tests",
        "control-plane-tests",
    ]
