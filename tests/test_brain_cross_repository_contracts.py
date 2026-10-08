"""Pinned sibling checkouts, not network/provider/live integration evidence.

Set OC_BRAIN_CONTRACT_ROOT and OC_FRONTEND_CONTRACT_ROOT to the separately
verified source checkouts. Missing siblings explicitly skip these checks.
"""

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from runtime.completion_receipt_contract import (
    CompletionReceiptError, evidence_digest, frontend_declares_full_sha_pattern,
    frontend_required_field_sets, load_contract, validate_completion_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def siblings():
    paths = [os.environ.get(name) for name in (
        "OC_BRAIN_CONTRACT_ROOT", "OC_FRONTEND_CONTRACT_ROOT",
    )]
    if not all(paths):
        pytest.skip("Current Brain/frontend sibling sources must be supplied explicitly")
    roots = tuple(Path(path).resolve(strict=True) for path in paths)
    assert all(root.is_dir() for root in roots)
    return roots


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def test_actual_brain_producer_passes_actual_brain_integration_consumer(siblings):
    brain, _ = siblings
    producer = _load(brain / "calyx_brain/reasoning_contracts.py", "isolated_brain_reasoning")
    consumer = _load(brain / "tools/validate_cross_system_integration_path.py", "isolated_brain_consumer")
    candidate = producer.CandidateKnowledge(
        "fixture:candidate", "fixture:taxon", "has_trait", "fixture:trait",
        ("fixture:evidence",), 0.5,
    )
    envelope = producer.build_reasoning_envelope(candidate, validation_pathways=("human_review",))
    consumer.validate_calyx_reasoning_envelope(envelope)
    assert envelope["human_review_required"] is True
    with pytest.raises(consumer.CrossSystemValidationError):
        consumer.validate_calyx_reasoning_envelope({
            **envelope, "automatic_scientific_publication_allowed": True,
        })


def test_backend_frontend_and_brain_preserve_completion_identity_and_authority(siblings):
    brain, frontend = siblings
    contract = load_contract()
    assert (ROOT / "contracts/oc-completion-receipt.v1.json").read_bytes() == (
        frontend / "contracts/oc-completion-receipt.v1.json"
    ).read_bytes()
    context = json.loads((brain / "contracts/autonomy_context_v1.json").read_text())
    assert context["required_evidence"] == contract["brain_required_evidence"]
    for binding in ("supervisor_discovery", "graph_issue_decision"):
        pinned = contract["bindings"]["frontend"][binding]
        source = (frontend / pinned["file"]).read_text()
        assert pinned["required_fields"] in frontend_required_field_sets(source)
    lease = contract["bindings"]["frontend"]["lease_sha_pattern"]
    assert frontend_declares_full_sha_pattern((frontend / lease["file"]).read_text())


@pytest.mark.parametrize("state", ["completed", "blocked", "failed", "not_executed"])
def test_exact_revision_receipt_cannot_hide_terminal_failure(siblings, state):
    _, frontend = siblings
    contract = json.loads((frontend / "contracts/oc-completion-receipt.v1.json").read_text())
    validation = {"fixture_only": True, "passed": state == "completed"}
    # This revision is the read-only source checkout's exact HEAD, not a claimed deployment.
    import subprocess
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    receipt = {
        "schema": "oc.completion-receipt.v1",
        "task_id": "fixture:static-validation", "declared_capability": "static-validation",
        "implementation_sha": sha, "run_id": "fixture:run", "lease_id": "fixture:lease",
        "execution_lane": "provider-free", "terminal_state": state,
        "test_evidence_digest": evidence_digest(validation),
        "provider_call_count": 0, "provider_cost_usd": 0, "changed_file_count": 0,
    }
    if state != "completed":
        with pytest.raises(CompletionReceiptError, match="failure_reason"):
            validate_completion_receipt(receipt, contract=contract)
        receipt["failure_reason"] = "Fixture-only terminal failure"
    checked = validate_completion_receipt(receipt, contract=contract)
    assert checked["terminal_state"] == state
    for bad_sha in ("main", sha[:7], sha.upper()):
        with pytest.raises(CompletionReceiptError):
            validate_completion_receipt({**receipt, "implementation_sha": bad_sha}, contract=contract)
