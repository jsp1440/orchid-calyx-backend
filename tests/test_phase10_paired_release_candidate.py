"""Current paired source -> HTTP -> PostgreSQL -> unchanged timer worker."""

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_brain_cross_repository_contracts import _load
from test_brain_module_lifecycle_contracts import (
    BRANCH,
    MODULE_TARGETS,
    REPOSITORY,
    disposable_program,  # noqa: F401 - imported pytest fixture
)
from test_brain_postgres_admission import (
    postgres,  # noqa: F401 - imported pytest fixture
)

from app.calyx_orchestrator import program_cycle
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob
from app.calyx_orchestrator.program_routes import router
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.database import get_db
from app.security import verify_owner_or_api_key
from runtime import program_autonomy_worker


def test_paired_packet_preflight_admission_leases_and_timer_completion(postgres, disposable_program, monkeypatch):  # noqa: F811
    source = Path(os.environ["OC_BRAIN_CONTRACT_ROOT"])
    producer = _load(source / "calyx_brain/reasoning_contracts.py", "phase10_reasoning")
    submission = _load(source / "calyx_brain/program_submission.py", "phase10_submission")
    workspace, _ = disposable_program
    app = FastAPI()
    app.include_router(router)

    def database():
        with Session(postgres) as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": "fixture-owner"}
    with TestClient(app) as client:
        def discovery():
            response = client.get("/programs/submission-capabilities")
            return response.status_code, response.json()

        def post(payload):
            return client.post("/programs", json=payload)

        for lane, path in MODULE_TARGETS.items():
            candidate = producer.CandidateKnowledge(
                f"fixture:{lane}", "fixture:subject", "has_trait", "fixture:object",
                (f"fixture:evidence:{lane}",), 0.5,
            )
            packet = producer.build_verification_program(
                candidate, repository=REPOSITORY, branch=BRANCH,
                files=[{"path": path, "sha256": hashlib.sha256((workspace / path).read_bytes()).hexdigest()}],
            )
            for _ in range(2):
                response = submission.submit_program(
                    packet, fetch_capabilities=discovery, post_program=post,
                )
                assert response.status_code == 201

    registry = AuthoritativeExecutorRegistry(workspace_root=workspace, repository_name=REPOSITORY)
    monkeypatch.setattr(program_cycle, "AuthoritativeExecutorRegistry", lambda: registry)
    factory = sessionmaker(bind=postgres)
    starts = []
    original_claim = PersistentProgramWorker.claim

    def observe_claim(self, **kwargs):
        job = original_claim(self, **kwargs)
        if job is not None:
            assert job.status == "running" and job.lease_owner == "phase10-worker"
            assert job.lease_expires_at > datetime.now(timezone.utc)
            assert job.lease_token
            starts.append((job.program_job_id, hashlib.sha256(job.lease_token.encode()).hexdigest()))
        return job

    monkeypatch.setattr(PersistentProgramWorker, "claim", observe_claim)
    calls = []

    def session_factory():
        if not calls:
            calls.append("simulated-storage-interruption")
            raise ConnectionError("fixture-only temporary storage interruption")
        return factory

    monkeypatch.setattr(program_autonomy_worker, "get_session_local", session_factory)
    policy = ProgramAutonomyPolicy.from_environ({
        "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
        "CALYX_PROGRAM_AUTONOMY_OWNER": "fixture-owner",
        "CALYX_PROGRAM_AUTONOMY_WORKER_ID": "phase10-worker",
        "CALYX_PROGRAM_AUTONOMY_POLL_SECONDS": "15",
        "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE": "1",
    })
    cycles, sleeps = [], []

    class Finished(BaseException):
        pass

    def observed_cycle(result):
        cycles.append(result)
        if len(cycles) == 11:
            raise Finished

    def accelerated_test_clock(seconds):
        assert seconds == 15
        sleeps.append(seconds)
        time.sleep(0.01)  # Explicit test-clock acceleration, not production cadence.

    try:
        program_autonomy_worker.run_forever(
            policy, sleeper=accelerated_test_clock, on_cycle=observed_cycle,
        )
    except Finished:
        pass
    assert cycles[0]["reason"] == "cycle_failed"
    assert len(sleeps) == 10
    assert all(cycle["cycle"]["completed_jobs"] == 1 for cycle in cycles[1:])
    assert len(starts) == len({job for job, _ in starts}) == len({lease for _, lease in starts}) == 10
    with Session(postgres) as db:
        assert db.scalar(select(func.count()).select_from(CalyxProgram)) == 5
        assert db.scalar(select(func.count()).select_from(CalyxProgramJob)) == 10
        assert all(program.status == "completed" for program in db.scalars(select(CalyxProgram)))
        for job in db.scalars(select(CalyxProgramJob)):
            assert job.outcome == "DELIVERED" and job.attempt_count == 1
            assert job.evidence_json and job.completed_at
            assert job.lease_owner is None and job.lease_token is None
