"""Local contract composition, NOT proof of live cross-module autonomy.

The pulse and executors are real. The admission mapping below is test scaffolding:
there is no claim that production automatically converts pulse candidates to
program jobs. Git workspaces and the persisted SQLite database are disposable.
External access is forbidden; cognitive reasoning uses the existing fixture store.
"""

import hashlib
import json
import socket
import subprocess
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import (
    governed_assignment_from_claimed_job,
)
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor_registry import (
    AuthoritativeExecutorRegistry,
    RegisteredExecutor,
)
from app.calyx_orchestrator.isolated_patch_executor import (
    ISOLATION_MARKER,
    ISOLATION_SCHEMA,
)
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.repository_evidence_executor import REPOSITORY_EVIDENCE_ROLE
from app.calyx_orchestrator.static_validation_executor import STATIC_VALIDATION_ROLE
from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.canonical_brain.orchestration import AgentDescriptor, GovernedOrchestrator
from app.canonical_brain.scheduler_bridge import (
    SchedulerJobMetadata,
    project_governed_queue,
)
from app.database import Base
from scripts import oc_brain_pulse, oc_work_materialize

SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/disposable-module-contracts"
MODULE_TARGETS = {
    "lexicon": "app/lexicon/intake.py",
    "literature": "app/calyx_conversation/literature_ingest.py",
    "research-station": "app/research_workspace/service.py",
    "atlas": "app/atlas_intelligence/assembler.py",
    "university-education": "app/university/ai_data_science.py",
}


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("External access forbidden in isolated lifecycle proof")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(oc_work_materialize, "github", denied)


@pytest.fixture
def disposable_program(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    # Real Git identity, not a made-up SHA or borrowed production checkout.
    for relative in ("AGENTS.md", "requirements.txt", *MODULE_TARGETS.values()):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((SOURCE_ROOT / relative).read_bytes())
    (root / ISOLATION_MARKER).write_text(json.dumps({
        "schema": ISOLATION_SCHEMA, "repository": REPOSITORY, "branch": BRANCH,
        "disposable": True, "workspace_write_authorized": True,
    }))
    for command in (
        ["git", "init", "-b", BRANCH],
        ["git", "add", "."],
        ["git", "-c", "user.name=Contract Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-m", "Disposable source snapshot"],
    ):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lifecycle.db'}")
    Base.metadata.create_all(engine, tables=[
        CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__,
    ])
    try:
        yield root, engine
    finally:
        engine.dispose()


def _request(key, candidate, **extra):
    return BuildAdmissionRequest(
        build_id=key, architecture_id=f"architecture:{candidate['lane']}",
        intent_ids=["intent:isolated-contract-verification"],
        decision_ids=[f"decision:{candidate['fingerprint']}"],
        source_uris=[f"fixture:brain-pulse/{candidate['fingerprint']}"],
        validation_plan_ids=["validation:repository-static-only"],
        deterministic_outputs=True, preserves_provenance=True,
        separates_evidence_from_inference=True, **extra,
    )


def _plan(root):
    # The real provider-free reasoning/discovery path, including product advisory.
    report = oc_brain_pulse.build_report()
    assert not report["errors"]
    assert report["authority"]["may_call_provider"] is False
    selected = [
        next(item for item in report["candidates"] if item["lane"] == lane)
        for lane in MODULE_TARGETS
    ]
    queue = GovernedBuildQueue()
    specs, metadata = [], []
    for candidate in selected:
        target = MODULE_TARGETS[candidate["lane"]]
        for role in (REPOSITORY_EVIDENCE_ROLE, STATIC_VALIDATION_ROLE):
            key = f"BUILD-{candidate['fingerprint']}-{role}"
            queue.submit(_request(key, candidate))
            specs.append(ProgramJobSpec(
                key, role, f"Fixture-only {role}: {candidate['lane']}", REPOSITORY,
                BRANCH, False,
                {"files": [{"path": target,
                            "sha256": hashlib.sha256((root / target).read_bytes()).hexdigest()}]},
            ))
            metadata.append(SchedulerJobMetadata(
                build_id=key, role_key=role, repository=REPOSITORY,
                branch=BRANCH, created_order=len(specs),
            ))
    dependencies = tuple((left.job_key, right.job_key) for left, right in pairwise(specs))
    return report, queue, specs, tuple(metadata), dependencies


def test_ten_module_checks_cross_admission_lease_execution_settlement_and_replenishment(disposable_program):
    root, engine = disposable_program
    report, queue, specs, metadata, dependencies = _plan(root)
    assert len(specs) == 10
    architectures = sorted({item.architecture_id for item in queue.snapshot().items})
    # Architecture routing is real; each program job must have a matching agent role.
    systems = {
        role: GovernedOrchestrator(queue, [AgentDescriptor(
            agent_id=f"agent:{role}", title=role, architecture_ids=architectures,
        )])
        for role in (REPOSITORY_EVIDENCE_ROLE, STATIC_VALIDATION_ROLE)
    }
    registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
    starts = []

    class LeaseWitness:
        def __init__(self, executor):
            self.executor = executor
            self.executor_key = executor.executor_key

        def execute(self, assignment):
            with Session(engine) as independent:
                row = independent.get(CalyxProgramJob, assignment.assignment_id)
                assert row.status == "running"
                assert row.lease_owner == "fixture-worker"
                assert row.lease_token and row.lease_expires_at
                assert row.attempt_count == 1
                # The losing worker cannot claim this leased dependency chain.
                assert PersistentProgramWorker(independent).claim(
                    owner="fixture-owner", worker_id="competing-worker", lease_seconds=300,
                    allowed_role_keys=registry.eligible_role_keys,
                ) is None
                # Store only a fingerprint, never a lease credential.
                starts.append((row.job_key, hashlib.sha256(row.lease_token.encode()).hexdigest()))
            return self.executor.execute(assignment)

    for role in registry.eligible_role_keys:
        registered = registry.require_authoritative(role)
        registry._by_role[role] = RegisteredExecutor(
            role, LeaseWitness(registered.executor), True, False,
            registered.workspace_mutation, registered.repository_code_execution,
        )
    with Session(engine) as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="fixture-owner", title="Five-module local contract chain",
            objective="Repository evidence and syntax checks, not scientific completion",
            jobs=specs, dependencies=dependencies,
        )
        repository.start(owner="fixture-owner", program_id=program.program_id)
        program_id = program.program_id

    for index, spec in enumerate(specs):
        schedule = project_governed_queue(
            queue=queue.snapshot(), metadata=metadata, dependencies=dependencies,
        )
        assert schedule.runnable_order == (spec.job_key,)
        system = systems[spec.role_key]
        assignment = system.assign(spec.job_key, datetime.now(timezone.utc))
        system.record_started(assignment.assignment_id, datetime.now(timezone.utc))
        # Reopen the DB every turn: no success can depend on the original session.
        with Session(engine) as db:
            row = db.scalar(select(CalyxProgramJob).where(CalyxProgramJob.job_key == spec.job_key))
            with pytest.raises(ValueError, match="ONLY_DURABLY_DELIVERED"):
                system.record_completed(
                    assignment.assignment_id, datetime.now(timezone.utc), db,
                    program_job_id=row.program_job_id, executor_role_key=spec.role_key,
                )
            result = run_deterministic_program_cycle(
                db, owner="fixture-owner", worker_id="fixture-worker", max_jobs=1, registry=registry,
            )
            assert not result.failures, result.failures
            assert result.completed_jobs == result.settled_jobs == result.attempted_jobs == 1
            assert result.jobs[0].job_key == spec.job_key
            assert result.jobs[0].executor_key != "autonomy_probe_v1"
            assert not result.failures
        with Session(engine) as db:
            row = db.get(CalyxProgramJob, result.jobs[0].program_job_id)
            assert row.status == "completed" and row.outcome == "DELIVERED"
            assert row.lease_token is None and row.lease_owner is None
            evidence = json.loads(row.evidence_json)
            output = evidence["output"]
            if spec.role_key == STATIC_VALIDATION_ROLE:
                assert output["results"][0]["syntax"] == "passed"
                assert output["repository_code_executed"] is False
                assert output["network_used"] is False
            else:
                assert output["file_count"] >= 2
                assert output["checkout_stable_during_scan"] is True
            canonical = system.record_completed(
                assignment.assignment_id, datetime.now(timezone.utc), db,
                program_job_id=row.program_job_id, executor_role_key=spec.role_key,
            )
            assert canonical.authoritative
            assert canonical.output_checksum == evidence["output_checksum"]
            if index + 1 < len(specs):
                downstream = db.scalar(select(CalyxProgramJob).where(
                    CalyxProgramJob.job_key == specs[index + 1].job_key,
                ))
                assert downstream.status == "queued" and downstream.attempt_count == 0
    assert [key for key, _ in starts] == [spec.job_key for spec in specs]
    assert len({fingerprint for _, fingerprint in starts}) == 10
    assert queue.snapshot().runnable_count == 0
    with Session(engine) as db:
        assert db.get(CalyxProgram, program_id).status == "completed"
        idle = run_deterministic_program_cycle(
            db, owner="fixture-owner", worker_id="fixture-worker", registry=registry,
        )
        assert idle.stop_reason == "idle" and idle.attempted_jobs == 0
    # A persistent scientific gap is still a gap. Repository checks do not resolve it.
    repeated = oc_brain_pulse.build_report()
    assert [item["fingerprint"] for item in repeated["candidates"]] == [
        item["fingerprint"] for item in report["candidates"]
    ]


@pytest.mark.parametrize("authority", [
    "publication_requested", "deployment_requested", "merge_requested",
    "production_graph_mutation_requested",
])
def test_admission_cannot_schedule_owner_governed_actions(authority):
    candidate = oc_brain_pulse.build_report()["candidates"][0]
    queue = GovernedBuildQueue()
    item = queue.submit(_request("BUILD-OWNER-GATE", candidate, **{authority: True}))
    assert item.status == "blocked"
    schedule = project_governed_queue(
        queue=queue.snapshot(), metadata=(SchedulerJobMetadata(
            build_id=item.build_id, role_key=STATIC_VALIDATION_ROLE, repository=REPOSITORY,
        ),), dependencies=(),
    )
    assert schedule.runnable_order == ()


def test_wrong_lease_and_receipt_identity_cannot_settle_or_replenish(disposable_program):
    from dataclasses import replace

    root, engine = disposable_program
    _, _, specs, _, dependencies = _plan(root)
    registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
    with Session(engine) as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="fixture-owner", title="Receipt fencing", objective="Reject mismatched settlement",
            jobs=specs[:2], dependencies=dependencies[:1],
        )
        repository.start(owner="fixture-owner", program_id=program.program_id)
        job = PersistentProgramWorker(db).claim(
            owner="fixture-owner", worker_id="fixture-worker", lease_seconds=300,
            allowed_role_keys=registry.eligible_role_keys,
        )
        assert job
        assignment = governed_assignment_from_claimed_job(db, owner="fixture-owner", job=job)
        receipt = registry.require_authoritative(job.role_key).executor.execute(assignment)
        for overrides in ({"lease_token": "wrong-fixture-token"}, {"worker_id": "other-worker"},
                          {"receipt": replace(receipt, job_key="wrong-build")}):
            kwargs = {
                "program_job_id": job.program_job_id,
                "worker_id": "fixture-worker",
                "lease_token": job.lease_token,
                "receipt": receipt,
            }
            kwargs.update(overrides)
            with pytest.raises((PermissionError, ValueError)):
                LeaseExecutionBridge(db).complete_from_receipt(**kwargs)
            db.refresh(job)
            assert job.status == "running" and job.outcome is None
            downstream = db.scalar(select(CalyxProgramJob).where(
                CalyxProgramJob.job_key == specs[1].job_key,
            ))
            assert downstream.status == "waiting" and downstream.attempt_count == 0


def test_failed_module_check_releases_lease_but_not_downstream_work(disposable_program):
    root, engine = disposable_program
    _, _, specs, _, _ = _plan(root)
    upstream, downstream = specs[1], specs[3]
    registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
    # Corrupt only the disposable input snapshot. Never relax the path/hash guard.
    target = upstream.inputs["files"][0]["path"]
    (root / target).write_text("# changed after admission\n")
    with Session(engine) as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="fixture-owner", title="Fail-closed module handoff",
            objective="Changed input cannot unlock another module",
            jobs=[upstream, downstream], dependencies=[(upstream.job_key, downstream.job_key)],
        )
        repository.start(owner="fixture-owner", program_id=program.program_id)
        result = run_deterministic_program_cycle(
            db, owner="fixture-owner", worker_id="fixture-worker", max_jobs=2, registry=registry,
        )
        assert result.completed_jobs == result.settled_jobs == 0
        assert result.attempted_jobs == 1
        assert result.failures[0]["code"] == f"STATIC_VALIDATION_HASH_MISMATCH:{target}"
        assert result.failures[0]["disposition"] == "retry_backoff"
    with Session(engine) as db:
        rows = {row.job_key: row for row in db.scalars(select(CalyxProgramJob))}
        assert rows[upstream.job_key].lease_token is None
        assert rows[upstream.job_key].outcome is None
        assert rows[downstream.job_key].status == "waiting"
        assert rows[downstream.job_key].attempt_count == 0
        idle = run_deterministic_program_cycle(
            db, owner="fixture-owner", worker_id="fixture-worker", registry=registry,
        )
        assert idle.attempted_jobs == 0
