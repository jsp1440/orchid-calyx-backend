import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import (
    AUTONOMY_PROBE_ROLE,
    AuthoritativeExecutorRegistry,
)
from app.calyx_orchestrator.models import CalyxJob
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.canonical_brain.orchestration import AgentDescriptor, GovernedOrchestrator
from app.database import Base


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


def durable_execution(build_id: str) -> tuple[Session, CalyxProgramJob, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxJob.__table__,
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
        ],
    )
    db = Session(engine)
    program = CalyxProgram(
        program_id="11111111-1111-1111-1111-111111111111",
        owner="operator:test",
        title="Canonical Brain durable completion",
        objective="Persist an authoritative executor receipt before Canonical completion.",
        status="running",
    )
    job = CalyxProgramJob(
        program_job_id="22222222-2222-2222-2222-222222222222",
        program_id=program.program_id,
        job_key=build_id,
        role_key=AUTONOMY_PROBE_ROLE,
        title=build_id,
        repository="jsp1440/orchid-calyx-backend",
        branch="autonomy/test",
        mutating=False,
        work_fingerprint="f" * 64,
        status="running",
        lease_owner="worker:test",
        lease_token="33333333-3333-3333-3333-333333333333",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        attempt_count=1,
    )
    db.add_all([program, job])
    db.commit()

    registered = AuthoritativeExecutorRegistry().require_authoritative(AUTONOMY_PROBE_ROLE)
    governed = GovernedAssignment(
        assignment_id=job.program_job_id,
        program_id=program.program_id,
        job_key=build_id,
        role_key=AUTONOMY_PROBE_ROLE,
        objective=build_id,
        inputs={"job": {"mutating_intent": False}},
        evidence_uris=(
            f"calyx:program/{program.program_id}",
            f"calyx:program-job/{job.program_job_id}",
        ),
    )
    receipt = registered.executor.execute(governed)
    completed = LeaseExecutionBridge(db).complete_from_receipt(
        program_job_id=job.program_job_id,
        worker_id="worker:test",
        lease_token="33333333-3333-3333-3333-333333333333",
        receipt=receipt,
    )
    assert completed.status == "completed"
    return db, completed, receipt


def test_deterministic_assignment_retry_returns_existing_assignment() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-ATLAS-002"), priority=10)
    system = orchestrator(queue)
    now = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)

    first = system.assign("BUILD-ATLAS-002", now)
    second = system.assign("BUILD-ATLAS-002", now + timedelta(seconds=5))

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


def test_durable_authoritative_job_can_complete_matching_probe_assignment() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE", datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc))
    started = system.record_started(
        assigned.assignment_id,
        datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc),
    )
    assert started.authoritative is False

    db, job, receipt = durable_execution("BUILD-PROBE")
    completed = system.record_completed(
        assigned.assignment_id,
        datetime(2026, 8, 6, 20, 3, tzinfo=timezone.utc),
        db,
        program_job_id=job.program_job_id,
        executor_role_key=AUTONOMY_PROBE_ROLE,
    )
    assert completed.outcome == "completed"
    assert completed.authoritative is True
    assert completed.executor_key == "autonomy_probe_v1"
    assert completed.output_checksum == receipt.output_checksum
    assert queue.get("BUILD-PROBE").status == "completed"


def test_unpersisted_or_incomplete_executor_result_cannot_complete_build() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE-PENDING", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE-PENDING", datetime.now(timezone.utc))
    system.record_started(assigned.assignment_id, datetime.now(timezone.utc))

    db, job, _ = durable_execution("ANOTHER-BUILD")
    with pytest.raises(ValueError, match="COMPLETION_BUILD_MISMATCH"):
        system.record_completed(
            assigned.assignment_id,
            datetime.now(timezone.utc),
            db,
            program_job_id=job.program_job_id,
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
    assert queue.get("BUILD-PROBE-PENDING").status == "running"


def test_durable_receipt_cannot_complete_mismatched_agent_role() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-ATLAS-003"))
    system = orchestrator(queue)
    assigned = system.assign("BUILD-ATLAS-003", datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc))
    system.record_started(assigned.assignment_id, datetime(2026, 8, 6, 20, 1, tzinfo=timezone.utc))

    db, job, _ = durable_execution("BUILD-ATLAS-003")
    with pytest.raises(PermissionError, match="COMPLETION_AGENT_ROLE_MISMATCH"):
        system.record_completed(
            assigned.assignment_id,
            datetime(2026, 8, 6, 20, 2, tzinfo=timezone.utc),
            db,
            program_job_id=job.program_job_id,
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
    assert queue.get("BUILD-ATLAS-003").status == "running"


def test_completion_requires_durable_evidence_uris() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE-NO-EVIDENCE", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE-NO-EVIDENCE", datetime.now(timezone.utc))
    system.record_started(assigned.assignment_id, datetime.now(timezone.utc))

    db, job, _ = durable_execution("BUILD-PROBE-NO-EVIDENCE")
    evidence = json.loads(job.evidence_json or "{}")
    evidence["evidence_uris"] = []
    job.evidence_json = json.dumps(evidence, sort_keys=True)
    db.commit()

    with pytest.raises(ValueError, match="DURABLE_EXECUTION_EVIDENCE_REQUIRED"):
        system.record_completed(
            assigned.assignment_id,
            datetime.now(timezone.utc),
            db,
            program_job_id=job.program_job_id,
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
    assert queue.get("BUILD-PROBE-NO-EVIDENCE").status == "running"


def test_cannot_complete_before_starting() -> None:
    queue = GovernedBuildQueue()
    queue.submit(request("BUILD-PROBE-SCHEDULED", architecture_id="architecture:brain"))
    system = probe_orchestrator(queue)
    assigned = system.assign("BUILD-PROBE-SCHEDULED", datetime.now(timezone.utc))
    db = Session(create_engine("sqlite+pysqlite:///:memory:"))

    with pytest.raises(ValueError, match="only running assignments"):
        system.record_completed(
            assigned.assignment_id,
            datetime.now(timezone.utc),
            db,
            program_job_id="missing",
            executor_role_key=AUTONOMY_PROBE_ROLE,
        )
