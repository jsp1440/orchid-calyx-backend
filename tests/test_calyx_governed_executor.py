from __future__ import annotations

import pytest

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import (
    DeterministicDryRunExecutor,
    ExecutionState,
    GovernedAssignment,
    canonical_checksum,
)


def assignment(**overrides):
    values = {
        "assignment_id": "assignment-1",
        "program_id": "program-1",
        "job_key": "brain-108",
        "role_key": "brain_engineer",
        "objective": "Validate a governed executor receipt.",
        "inputs": {"alpha": 1, "beta": [2, 3]},
        "requested_capabilities": ("validate_input", "produce_receipt"),
        "evidence_uris": ("github:issue/437", "brain:build/BUILD-BRAIN-108"),
        "timeout_seconds": 60,
    }
    values.update(overrides)
    return GovernedAssignment(**values)


def test_dry_run_receipt_is_deterministic_and_verifiable():
    executor = DeterministicDryRunExecutor()
    first = executor.execute(assignment())
    second = executor.execute(assignment())

    assert first == second
    assert first.state == ExecutionState.DELIVERED
    assert first.outcome == TerminalOutcome.DELIVERED
    assert first.output["side_effects"] == []
    assert first.input_checksum == canonical_checksum({"alpha": 1, "beta": [2, 3]})
    first.verify()


def test_input_checksum_mismatch_fails_closed():
    with pytest.raises(ValueError, match="ASSIGNMENT_INPUT_CHECKSUM_MISMATCH"):
        DeterministicDryRunExecutor().execute(assignment(input_checksum="not-the-checksum"))


@pytest.mark.parametrize(
    "capability",
    ["shell", "network", "merge", "deploy", "publish", "credential_access", "production_graph_mutation"],
)
def test_prohibited_capabilities_are_blocked(capability):
    receipt = DeterministicDryRunExecutor().execute(
        assignment(requested_capabilities=("produce_receipt", capability))
    )

    assert receipt.state == ExecutionState.BLOCKED
    assert receipt.outcome == TerminalOutcome.BLOCKED
    assert receipt.blocker_code == "PROHIBITED_CAPABILITY"
    assert receipt.output["executed"] is False


def test_unknown_capability_is_blocked():
    receipt = DeterministicDryRunExecutor().execute(
        assignment(requested_capabilities=("future_unregistered_capability",))
    )
    assert receipt.blocker_code == "UNSUPPORTED_CAPABILITY"
    assert receipt.state == ExecutionState.BLOCKED


def test_cancelled_assignment_returns_cancellation_receipt():
    receipt = DeterministicDryRunExecutor().execute(assignment(cancelled=True))
    assert receipt.state == ExecutionState.CANCELLED
    assert receipt.outcome == TerminalOutcome.CANCELLED
    assert receipt.output["executed"] is False


def test_nonpositive_timeout_fails_closed():
    receipt = DeterministicDryRunExecutor().execute(assignment(timeout_seconds=0))
    assert receipt.state == ExecutionState.TIMED_OUT
    assert receipt.outcome == TerminalOutcome.BLOCKED
    assert receipt.blocker_code == "INVALID_OR_EXPIRED_TIMEOUT"


def test_evidence_uris_are_deduplicated_in_order():
    receipt = DeterministicDryRunExecutor().execute(
        assignment(evidence_uris=("github:issue/437", "github:issue/437", "brain:build/108"))
    )
    assert receipt.evidence_uris == ("github:issue/437", "brain:build/108")


def test_invalid_evidence_uri_is_rejected():
    with pytest.raises(ValueError, match="INVALID_EVIDENCE_URI"):
        DeterministicDryRunExecutor().execute(assignment(evidence_uris=("not-a-uri",)))
