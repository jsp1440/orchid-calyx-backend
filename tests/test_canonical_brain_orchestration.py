from datetime import datetime, timezone

import pytest

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import (
    AUTONOMY_PROBE_ROLE,
    AuthoritativeExecutorRegistry,
)
from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.canonical_brain.orchestration import AgentDescriptor, GovernedOrchestrator


def request(
    build_id: str,
    architecture_id: str = "architecture:atlas",
    **overrides: object,
) -> BuildAdmissionRequest:
    values = {
        "build_id": build_id,
        "architecture_id": architecture_id,
        "intent_ids": ["intent:preserve-biodiversity"],
        "decision_ids": ["decision:atlas-earth-systems"],
        "source_uris": ["github://issue/419"],
        "validation_plan_ids": ["validation:atlas-focused"],
        "deterministic_outputs": True,
        "preserves_provenance": True,
        "separates_evidence_from_inference": True,
    }
    values.update(overrides)
    return BuildAdmissionRequest(**values)


def orchestrator(queue: GovernedBuildQueue) -> GovernedOrchestrator:
    return GovernedOrchestrator(
        queue,
        [
            AgentDescriptor(
                agent_id="agent:atlas-engineer",
                title="Atlas Engineer",
                architecture_ids=["architecture:atlas"],
            ),
            AgentDescriptor(
                agent_id="agent:brain-engineer",
                title="Brain Engineer",
                architecture_ids=["architecture:brain"],
            ),
        ],
    )


def probe_orchestrator(queue: GovernedBuildQueue) -> GovernedOrchestrator:
    return GovernedOrchestrator(
        queue,
        [
            AgentDescriptor(
                agent_id="agent:autonomy-probe",
                title="Autonomy Probe",
                architecture_ids=["architecture:brain"],
            )
        ],
    )


def authoritative_receipt(assignment):
    registry = AuthoritativeExecutorRegistry()
    registered = registry.require_authoritative(AUTONOMY_PROBE_ROLE)
    governed = GovernedAssignment(
        assignment_id=assignment.assignment_id,
        program_id="program:canonical-brain-test",
        job_key=assignment.build_id,
        role_key=AUTONOMY_PROBE_ROLE,
        objective=assignment.build_id,
        inputs={"job": {"mutating_intent": False}},
        evidence_uris=("github://commit/example", "ci://run/example"),
    )
    return registered.executor.execute(governed)


def test_deterministic_assignment_uses_enabled_matching_agent() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-ATLAS-002"), priority=10)
    system = orchestrator(queue)
    now = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)

    first = system.assign("BUILD-ATLAS-002", now)
    second = system.assignments()[0]

    assert first == second
    assert first.agent_id == "agent:atlas-engineer"
    assert queue.get("BUILD-ATLAS-002").status == "scheduled"


def test_blocked_build_cannot_be_assigned() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-BLOCKED", merge_requested=True))

    with pytest.raises(ValueError, match="only admitted builds"):
        orchestrator(queue).assign("BUILD-BLOCKED", datetime.now(timezone.utc))


def test_missing_capable_agent_fails_closed() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-CONSERVATORY", architecture_id="architecture:conservatory"))

    with pytest.raises(ValueError, match="no enabled agent"):
        orchestrator(queue).assign("BUILD-CONSERVATORY", datetime.now(timezone.utc))


def test_authoritative_probe_receipt_can_complete_matching_probe_assignment() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE", datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc))

    started = system.record_started(
        assigned.assignment_id,
        datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc),
    )
    assert started.outcome == "started"
    assert started.authoritative is False

    receipt = authoritative_receipt(assigned)
    completed = system.record_completed(
        assigned.assignment_id,
        datetime(2026, 8, 6, 20, 3, tzinfo=timezone.utc),
        receipt,
        executor_role_key=AUTONOMY_PROBE_ROLE,
    )
    assert completed.outcome == "completed"
    assert completed.authoritative is True
    assert completed.executor_key == "autonomy_probe_v1"
    assert completed.output_checksum == receipt.output_checksum
    assert queue.get("BUILD-PROBE").status == "completed"


def test_authoritative_receipt_cannot_complete_mismatched_agent_role() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-ATLAS-003"))
    system = orchestrator(queue)
    assigned = system.assign("BUILD-ATLAS-003", datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc))
    system.record_started(assigned.assignment_id, datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc))

    receipt = authoritative_receipt(assigned)
    with pytest.raises(PermissionError, match="COMPLETION_AGENT_ROLE_MISMATCH"):
        system.record_completed(
            assigned.assignment_id,
            datetime(2026, 8, 6, 20, 2, tzinfo=timezone.utc),
            receipt,
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
    assert queue.get("BUILD-ATLAS-003").status == "running"


def test_completion_requires_evidence_from_authoritative_receipt() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE-NO-EVIDENCE", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE-NO-EVIDENCE", datetime.now(timezone.utc))
    system.record_started(assigned.assignment_id, datetime.now(timezone.utc))
    receipt = authoritative_receipt(assigned)
    incomplete = receipt.__class__(
        assignment_id=receipt.assignment_id,
        program_id=receipt.program_id,
        job_key=receipt.job_key,
        executor_key=receipt.executor_key,
        state=receipt.state,
        outcome=receipt.outcome,
        input_checksum=receipt.input_checksum,
        output_checksum=receipt.output_checksum,
        output=receipt.output,
        evidence_uris=(),
        blocker_code=receipt.blocker_code,
    )

    with pytest.raises(ValueError, match="requires evidence"):
        system.record_completed(
            assigned.assignment_id,
            datetime.now(timezone.utc),
            incomplete,
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
    assert queue.get("BUILD-PROBE-NO-EVIDENCE").status == "running"


def test_cannot_complete_before_starting() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE-SCHEDULED", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE-SCHEDULED", datetime.now(timezone.utc))
    receipt = authoritative_receipt(assigned)

    with pytest.raises(ValueError, match="only running assignments"):
        system.record_completed(
            assigned.assignment_id,
            datetime.now(timezone.utc),
            receipt,
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
