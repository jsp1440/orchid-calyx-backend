"""The governor must be observable, not only runnable.

Before these endpoints existed the persisted completion path could be started
and stepped but never *watched*. ``enqueue`` returned a job_id, ``run-once``
returned the executing worker's own view of the step it had just taken, and
nothing else read the row. A job parked in ``queued`` with a future
``next_attempt_at`` - which is exactly what WAITING_FOR_CI looks like between
polls - was indistinguishable from a job that was never created.

That is fatal for AGENT-007, which has to evidence every state transition
including the ones where the governor is deliberately doing nothing.

These reads must stay reads. A certification surface that advances the thing it
is measuring is not evidence, so the no-mutation property is asserted directly
rather than assumed from the HTTP verb.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.calyx_engineering.completion_scheduler import (
    ENGINEERING_COMPLETION_JOB_TYPE,
    EngineeringCompletionScheduler,
)
from app.calyx_engineering.routes import router
from app.calyx_orchestrator.models import CalyxJob
from app.database import Base, get_db
from app.security import verify_owner_or_api_key

OWNER = "certification-owner"


class FakeGitHubClient:
    pass


@pytest.fixture()
def db():
    # TestClient serves requests on another thread; a default in-memory SQLite
    # engine refuses the cross-thread handle and every route test errors out.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[CalyxJob.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": OWNER}
    return TestClient(app)


def _enqueue(db, *, pull_request_number: int = 1043, owner: str = OWNER) -> CalyxJob:
    return EngineeringCompletionScheduler(db, FakeGitHubClient()).enqueue(
        owner=owner,
        pull_request_number=pull_request_number,
        repair_paths=["tests/test_build_088e_publication_operational_readiness.py"],
        objective="Repair the deterministic certification failure only.",
        repairs_authorized=True,
        required_checks=["BUILD-088E Validation"],
    )


def test_the_job_type_filter_matches_what_the_scheduler_actually_writes(db):
    """Guards the defect that would make every read below silently empty.

    The routes must use the scheduler's constant. A hardcoded literal that
    disagrees with it produces endpoints that return 404 and [] forever while
    looking entirely correct.
    """
    job = _enqueue(db)
    assert job.job_type == ENGINEERING_COMPLETION_JOB_TYPE


def test_a_queued_job_is_readable_before_anything_executes(db, client):
    job = _enqueue(db)
    response = client.get(f"/engineering/completion-jobs/{job.job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.job_id
    assert body["status"] == "queued"
    assert body["pull_request_number"] == 1043
    assert body["required_checks"] == ["BUILD-088E Validation"]
    assert body["attempt_count"] == 0


def test_reading_a_job_does_not_advance_it(db, client):
    """The property that makes this evidence rather than participation."""
    job = _enqueue(db)
    before = (job.status, job.attempt_count, job.lease_owner, job.result_json)
    for _ in range(3):
        assert client.get(f"/engineering/completion-jobs/{job.job_id}").status_code == 200
        assert client.get("/engineering/completion-jobs").status_code == 200
    db.refresh(job)
    assert (job.status, job.attempt_count, job.lease_owner, job.result_json) == before


def test_a_waiting_job_is_distinguishable_from_a_job_that_never_existed(db, client):
    """The exact opacity these endpoints were added to remove."""
    job = _enqueue(db)
    job.result_json = json.dumps({"state": "waiting_for_ci", "next_action": "recheck_after_ci"})
    db.commit()

    body = client.get(f"/engineering/completion-jobs/{job.job_id}").json()
    assert body["state"] == "waiting_for_ci"
    assert body["next_action"] == "recheck_after_ci"
    assert body["receipt"] is not None

    missing = client.get("/engineering/completion-jobs/job-that-does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "ENGINEERING_COMPLETION_JOB_NOT_FOUND"


def test_every_read_restates_that_the_governor_holds_no_merge_or_deploy_authority(db, client):
    """A 'completed' job must never read as 'merged'.

    READY_FOR_MERGE terminates the governor. Restating it on the row itself
    means no consumer has to infer the boundary from a status string.
    """
    job = _enqueue(db)
    job.status = "completed"
    job.result_json = json.dumps({"state": "ready_for_merge", "next_action": "evaluate_merge_policy"})
    db.commit()
    body = client.get(f"/engineering/completion-jobs/{job.job_id}").json()
    assert body["autonomous_merge"] is False
    assert body["deployment"] is False
    assert body["mutating"] is False


def test_a_blocked_job_surfaces_why_it_stopped(db, client):
    job = _enqueue(db)
    job.status = "blocked_approval"
    job.approval_required = True
    job.approval_class = "engineering_repair"
    job.error_code = "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"
    db.commit()
    body = client.get(f"/engineering/completion-jobs/{job.job_id}").json()
    assert body["status"] == "blocked_approval"
    assert body["approval_required"] is True
    assert body["approval_class"] == "engineering_repair"
    assert body["error_code"] == "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"


def test_jobs_are_listable_and_filterable_by_pull_request(db, client):
    _enqueue(db, pull_request_number=1043)
    _enqueue(db, pull_request_number=1044)
    every = client.get("/engineering/completion-jobs").json()
    assert every["count"] == 2
    assert every["mutating"] is False

    one = client.get("/engineering/completion-jobs", params={"pull_request_number": 1043}).json()
    assert one["count"] == 1
    assert one["jobs"][0]["pull_request_number"] == 1043


def test_a_job_belonging_to_another_owner_is_not_readable(db, client):
    other = _enqueue(db, owner="someone-else")
    assert client.get(f"/engineering/completion-jobs/{other.job_id}").status_code == 404
    assert client.get("/engineering/completion-jobs").json()["count"] == 0


def test_a_malformed_row_degrades_instead_of_failing_the_diagnostic_read(db, client):
    """The read that diagnoses a corrupt job must not be broken by it."""
    job = _enqueue(db)
    job.request_text = "{not json"
    job.result_json = "{also not json"
    db.commit()
    body = client.get(f"/engineering/completion-jobs/{job.job_id}").json()
    assert body["job_id"] == job.job_id
    assert body["pull_request_number"] is None
    assert body["required_checks"] == []
    assert body["receipt"] is None
