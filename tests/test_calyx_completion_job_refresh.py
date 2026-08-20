from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_engineering.completion_scheduler import EngineeringCompletionScheduler
from app.calyx_orchestrator.models import CalyxJob
from app.database import Base


class FakeGitHubClient:
    pass


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CalyxJob.__table__])
    return sessionmaker(bind=engine)()


def _scheduler(db):
    return EngineeringCompletionScheduler(db, FakeGitHubClient())


def test_reenqueue_refreshes_stale_queued_job_payload():
    db = _session()
    scheduler = _scheduler(db)
    first = scheduler.enqueue(
        owner="owner",
        pull_request_number=1043,
        repair_paths=["tests/example.py"],
        objective="Initial certification request.",
        repairs_authorized=True,
        required_checks=["string"],
    )
    first.next_attempt_at = first.created_at
    db.commit()

    refreshed = scheduler.enqueue(
        owner="owner",
        pull_request_number=1043,
        repair_paths=["tests/example.py"],
        objective="Repair the intended BUILD-088E certification failure.",
        repairs_authorized=True,
        required_checks=["BUILD-088E Validation"],
        priority=7,
    )

    assert refreshed.job_id == first.job_id
    payload = json.loads(refreshed.request_text)
    assert payload["required_checks"] == ["BUILD-088E Validation"]
    assert payload["objective"] == "Repair the intended BUILD-088E certification failure."
    assert refreshed.priority == 7
    assert refreshed.next_attempt_at is None


def test_reenqueue_does_not_mutate_running_job_with_different_payload():
    db = _session()
    scheduler = _scheduler(db)
    job = scheduler.enqueue(
        owner="owner",
        pull_request_number=1043,
        repair_paths=["tests/example.py"],
        objective="Initial certification request.",
        repairs_authorized=True,
        required_checks=["BUILD-088E Validation"],
    )
    job.status = "running"
    db.commit()

    with pytest.raises(ValueError, match="ENGINEERING_COMPLETION_RUNNING_JOB_CONFLICT"):
        scheduler.enqueue(
            owner="owner",
            pull_request_number=1043,
            repair_paths=["tests/example.py"],
            objective="Different objective while worker owns the job.",
            repairs_authorized=True,
            required_checks=["BUILD-088E Validation"],
        )
