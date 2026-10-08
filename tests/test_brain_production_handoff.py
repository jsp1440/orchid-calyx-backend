"""Real producer -> program API -> existing executors, with isolated fixtures."""

import hashlib
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob
from app.calyx_orchestrator.program_routes import router
from app.database import get_db
from app.security import verify_owner_or_api_key
from test_brain_cross_repository_contracts import _load
from test_brain_module_lifecycle_contracts import (
    BRANCH,
    MODULE_TARGETS,
    REPOSITORY,
    disposable_program,  # noqa: F401 - pytest fixture reused, not copied
)


def test_actual_brain_packets_execute_ten_source_checks_without_test_job_mapping(disposable_program):  # noqa: F811 - imported pytest fixture
    source = os.environ.get("OC_BRAIN_CONTRACT_ROOT")
    if not source:
        pytest.skip("Explicit current Brain companion source required")
    producer = _load(Path(source) / "calyx_brain/reasoning_contracts.py", "handoff_brain")
    root, engine = disposable_program
    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session
    # Authentication is supplied only by this disposable test application.
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": "fixture-owner"}
    with TestClient(app) as client, Session(engine) as db:
        for lane, path in MODULE_TARGETS.items():
            candidate = producer.CandidateKnowledge(
                f"fixture:{lane}", "fixture:subject", "has_trait", "fixture:object",
                (f"fixture:evidence:{lane}",), 0.5,
            )
            packet = producer.build_verification_program(
                candidate, repository=REPOSITORY, branch=BRANCH,
                files=[{"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}],
            )
            # No translation into ProgramJobSpec or test-only role mapping.
            first = client.post("/programs", json=packet)
            replay = client.post("/programs", json=packet)
            assert first.status_code == replay.status_code == 201
        assert db.scalar(select(func.count()).select_from(CalyxProgram)) == 5
        assert db.scalar(select(func.count()).select_from(CalyxProgramJob)) == 10
        registry = AuthoritativeExecutorRegistry(workspace_root=root, repository_name=REPOSITORY)
        for _ in range(10):
            cycle = run_deterministic_program_cycle(
                db, owner="fixture-owner", worker_id="fixture-worker",
                max_jobs=1, registry=registry,
            )
            assert cycle.attempted_jobs == cycle.completed_jobs == 1
            assert not cycle.error and not cycle.failures
        jobs = db.scalars(select(CalyxProgramJob)).all()
        assert all(job.outcome == "DELIVERED" and job.attempt_count == 1 for job in jobs)
        assert all(job.lease_owner is None and job.lease_token is None for job in jobs)
        assert all(program.status == "completed" for program in db.scalars(select(CalyxProgram)))
