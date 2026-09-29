"""Cross-repository completion receipt contract.

A completion receipt must carry an exact commit identity and a test-evidence
digest, and every consumer must fail closed on anything else. The contract file
is mirrored in the frontend repository; when a checkout of that repository (or
of the Brain) is available through ``OC_FRONTEND_CHECKOUT`` / ``OC_BRAIN_CHECKOUT``
the live sources are compared, otherwise the pinned bindings in the contract are.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from runtime.completion_receipt_contract import (
    CONTRACT_PATH,
    REPO_ROOT,
    CompletionReceiptError,
    canonical_json,
    evidence_digest,
    frontend_declares_full_sha_pattern,
    frontend_required_field_sets,
    load_contract,
    validate_completion_receipt,
)

CONTRACT = load_contract()
FRONTEND = CONTRACT["bindings"]["frontend"]
BRAIN_EVIDENCE = CONTRACT["brain_required_evidence"]
FULL_SHA = re.compile(r"\b[a-f0-9]{40}\b")
FULL_DIGEST = re.compile(r"\b[a-f0-9]{64}\b")


def _well_formed() -> dict:
    evidence = {"pytest": "tests/test_x.py: 12 passed", "ruff": "clean"}
    return {
        "schema": "oc.completion-receipt.v1",
        "task_id": "issue-1592:retrieve-evidence",
        "declared_capability": "provider-free-validation",
        "implementation_sha": "bcf6bcb1e873bc5fe05b7c339cb30a74bbc55fd3",
        "run_id": "36092029213:1",
        "lease_id": "lease-7f3c",
        "execution_lane": "provider-free",
        "terminal_state": "completed",
        "test_evidence_digest": evidence_digest(evidence),
        "provider_call_count": 0,
        "provider_cost_usd": 0,
        "changed_file_count": 3,
        "results": {"tests": "12 passed"},
    }


def _checkout(env_name: str) -> Path | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path if path.is_dir() else None


# --- the validator itself ---------------------------------------------------


def test_well_formed_receipt_is_accepted_and_normalised():
    receipt = _well_formed()
    validated = validate_completion_receipt(receipt)
    assert validated["implementation_sha"] == receipt["implementation_sha"]
    assert validated["test_evidence_digest"] == receipt["test_evidence_digest"]
    assert validated["terminal_state"] == "completed"


def test_digest_is_deterministic_and_order_independent():
    a = {"tests": ["x", "y"], "ruff": "clean"}
    b = {"ruff": "clean", "tests": ["x", "y"]}
    assert evidence_digest(a) == evidence_digest(b)
    assert FULL_DIGEST.fullmatch(evidence_digest(a))
    assert canonical_json(a) == canonical_json(b)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r.pop("implementation_sha"), "missing_field"),
        (lambda r: r.pop("test_evidence_digest"), "missing_field"),
        (lambda r: r.pop("run_id"), "missing_field"),
        (lambda r: r.pop("lease_id"), "missing_field"),
        (lambda r: r.pop("changed_file_count"), "missing_field"),
        (lambda r: r.update(implementation_sha="bcf6bcb1"), "pattern_mismatch"),
        (
            lambda r: r.update(implementation_sha=r["implementation_sha"].upper()),
            "pattern_mismatch",
        ),
        (lambda r: r.update(implementation_sha="main"), "pattern_mismatch"),
        (lambda r: r.update(implementation_sha=""), "pattern_mismatch"),
        (lambda r: r.update(test_evidence_digest="deadbeef"), "pattern_mismatch"),
        (lambda r: r.update(terminal_state="done"), "not_in_enum"),
        (lambda r: r.update(execution_lane="magic"), "not_in_enum"),
        (lambda r: r.update(provider_call_count=-1), "below_minimum"),
        (lambda r: r.update(provider_call_count="0"), "wrong_type"),
        (lambda r: r.update(provider_call_count=True), "wrong_type"),
        (lambda r: r.update(changed_file_count=1.5), "wrong_type"),
        (lambda r: r.update(terminal_state="blocked"), "missing_field"),
        (
            lambda r: r.update(schema="oc.autonomy-durable-proof.v1"),
            "receipt_schema_mismatch",
        ),
        (lambda r: r.pop("schema"), "receipt_schema_mismatch"),
    ],
)
def test_malformed_receipts_fail_closed(mutate, code):
    receipt = _well_formed()
    mutate(receipt)
    with pytest.raises(CompletionReceiptError) as excinfo:
        validate_completion_receipt(receipt)
    assert excinfo.value.code == code


def test_non_object_receipts_fail_closed():
    for payload in (None, "done", 42, ["done"], b"done"):
        with pytest.raises(CompletionReceiptError) as excinfo:
            validate_completion_receipt(payload)
        assert excinfo.value.code == "receipt_not_object"


def test_blocked_receipt_needs_a_failure_reason_and_is_then_accepted():
    receipt = _well_formed()
    receipt["terminal_state"] = "blocked"
    receipt["failure_reason"] = "owner-gated: production activation requires approval"
    assert validate_completion_receipt(receipt)["failure_reason"].startswith(
        "owner-gated"
    )


# --- the negative fixture: a "PASS" that names no revision ------------------

DURABLE_PROOF = REPO_ROOT / "artifacts" / "autonomy-durable-proof.json"


@pytest.mark.skipif(not DURABLE_PROOF.exists(), reason="artifact not present")
def test_autonomy_durable_proof_artifact_is_not_a_completion_receipt():
    """artifacts/autonomy-durable-proof.json claims PASS, 10/10 cycles, and names
    no commit SHA, run id or evidence digest anywhere. That is exactly the shape a
    consumer must refuse: it cannot be tied to any revision."""
    text = DURABLE_PROOF.read_text(encoding="utf-8")
    proof = json.loads(text)
    assert proof.get("status") == "PASS"
    assert not FULL_SHA.search(text), (
        "a full commit SHA appeared; update this fixture's premise"
    )
    assert not FULL_DIGEST.search(text)

    with pytest.raises(CompletionReceiptError) as excinfo:
        validate_completion_receipt(proof)
    assert excinfo.value.code == "receipt_schema_mismatch"

    cycles = proof.get("cycles") or []
    assert cycles, "the proof declares cycles; each must be individually rejected"
    for cycle in cycles:
        with pytest.raises(CompletionReceiptError):
            validate_completion_receipt(cycle)


# --- the contract file itself -----------------------------------------------


def test_every_contract_field_maps_to_a_frontend_field_and_brain_evidence_is_covered():
    fields = CONTRACT["receipt_fields"]
    frontend_names = {spec["frontend_field"] for spec in fields.values()}
    assert len(frontend_names) == len(fields), "frontend_field names must be unique"
    covered = {spec["brain_evidence"] for spec in fields.values()} - {None}
    assert covered == set(BRAIN_EVIDENCE)


def test_pinned_frontend_required_fields_are_covered_by_the_contract():
    frontend_names = {
        spec["frontend_field"] for spec in CONTRACT["receipt_fields"].values()
    }
    for binding in ("supervisor_discovery", "graph_issue_decision"):
        required = set(FRONTEND[binding]["required_fields"])
        assert "implementationSha" in required
        assert required <= frontend_names, f"{binding}: {required - frontend_names}"
    assert (
        FRONTEND["lease_sha_pattern"]["pattern"]
        == CONTRACT["receipt_fields"]["implementation_sha"]["pattern"]
    )


def test_backend_canonical_context_required_evidence_matches_the_contract():
    context = json.loads(
        (REPO_ROOT / "contracts" / "oc-autonomy-context.v1.json").read_text()
    )
    assert context["required_evidence"] == BRAIN_EVIDENCE


# --- live cross-repository comparison (when a checkout is provided) ---------


def test_frontend_sources_match_the_pinned_bindings():
    frontend = _checkout("OC_FRONTEND_CHECKOUT")
    if frontend is None:
        pytest.skip("OC_FRONTEND_CHECKOUT not set; pinned bindings compared instead")
    for binding in ("supervisor_discovery", "graph_issue_decision"):
        source = (frontend / FRONTEND[binding]["file"]).read_text(encoding="utf-8")
        found = frontend_required_field_sets(source)
        assert FRONTEND[binding]["required_fields"] in found, (
            f"{FRONTEND[binding]['file']} requiredFields diverged from the contract: {found}"
        )
    lease_source = (frontend / FRONTEND["lease_sha_pattern"]["file"]).read_text(
        encoding="utf-8"
    )
    assert frontend_declares_full_sha_pattern(lease_source)

    mirrored = frontend / FRONTEND["contract_copy"]
    assert mirrored.exists(), (
        "frontend must carry contracts/oc-completion-receipt.v1.json"
    )
    assert json.loads(mirrored.read_text(encoding="utf-8")) == CONTRACT, (
        "frontend contract copy diverged from the backend contract"
    )
    context_copy = frontend / "contracts" / "oc-autonomy-context.v1.json"
    if context_copy.exists():
        assert (
            json.loads(context_copy.read_text())["required_evidence"] == BRAIN_EVIDENCE
        )


def test_brain_canonical_context_matches_the_contract():
    brain = _checkout("OC_BRAIN_CHECKOUT")
    if brain is None:
        pytest.skip(
            "OC_BRAIN_CHECKOUT not set; pinned brain_required_evidence compared instead"
        )
    context = json.loads((brain / "contracts" / "autonomy_context_v1.json").read_text())
    assert context["required_evidence"] == BRAIN_EVIDENCE


def test_contract_file_is_canonical_json_on_disk():
    raw = CONTRACT_PATH.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw) == CONTRACT
