from datetime import datetime, timezone

import pytest

from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.canonical_brain.orchestration import AgentDescriptor, GovernedOrchestrator


def request(build_id: str, architecture_id: str = "architecture:atlas", **overrides: object) -> BuildAdmissionRequest:
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


def test_execution_receipts_require_order_and_evidence() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-ATLAS-003"))
    system = orchestrator(queue)
    assigned = system.assign("BUILD-ATLAS-003", datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc))

    started = system.record_started(assigned.assignment_id, datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc))
    assert started.outcome == "started"
    assert queue.get("BUILD-ATLAS-003").status == "running"

    with pytest.raises(ValueError, match="requires evidence"):
        system.record_completed(
            assigned.assignment_id,
            datetime(2026, 8, 6, 20, 2, tzinfo=timezone.utc),
            [],
            "short",
        )

    completed = system.record_completed(
        assigned.assignment_id,
        datetime(2026, 8, 6, 20, 3, tzinfo=timezone.utc),
        ["github://commit/example", "ci://run/example"],
        "a" * 64,
    )
    assert completed.outcome == "completed"
    assert completed.output_checksum == "a" * 64
    assert queue.get("BUILD-ATLAS-003").status == "completed"


def test_cannot_complete_before_starting() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-ATLAS-004"))
    system = orchestrator(queue)
    assigned = system.assign("BUILD-ATLAS-004", datetime.now(timezone.utc))

    with pytest.raises(ValueError, match="only running assignments"):
        system.record_completed(
            assigned.assignment_id,
            datetime.now(timezone.utc),
            ["github://commit/example"],
            "b" * 64,
        )
