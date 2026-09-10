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
