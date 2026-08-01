from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_agent.service import CalyxAgentService
from app.calyx_orchestrator.models import CalyxFinding, CalyxJob, utcnow
from app.calyx_orchestrator.service import CalyxOrchestrator
from app.calyx_orchestrator.worker import enabled
from app.database import Base


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_seed_overnight_is_durable_and_idempotent(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    first = service.seed_overnight(owner="owner")
    second = service.seed_overnight(owner="owner")
    assert len(first) == 7
    assert {job.job_id for job in first} == {job.job_id for job in second}
    assert db.query(CalyxJob).count() == 7


def test_claim_execute_and_finding_provenance(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    service.seed_overnight(owner="owner")
    job = service.claim(worker_id="worker-1", lease_seconds=120)
    assert job is not None
    token = job.lease_token
    assert token
    completed = service.execute(job, worker_id="worker-1", lease_token=token)
    assert completed.status == "completed"
    assert completed.result_json
    assert db.query(CalyxFinding).count() >= 1


def test_stale_worker_cannot_commit(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    service.seed_overnight(owner="owner")
    job = service.claim(worker_id="worker-1")
    assert job is not None
    try:
        service.execute(job, worker_id="worker-2", lease_token="wrong")
    except PermissionError as exc:
        assert str(exc) == "STALE_WORKER_LEASE"
    else:
        raise AssertionError("stale worker lease was accepted")


def test_expired_running_job_is_reclaimed(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    service.seed_overnight(owner="owner")
    first = service.claim(worker_id="worker-1", lease_seconds=120)
    assert first is not None
    first.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    reclaimed = service.claim(worker_id="worker-2", lease_seconds=120)
    assert reclaimed is not None
    assert reclaimed.job_id == first.job_id
    assert reclaimed.lease_owner == "worker-2"
    assert reclaimed.attempt_count == 2


def test_seeded_release_readiness_is_read_only(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    jobs = service.seed_overnight(owner="owner")
    release_job = next(job for job in jobs if job.job_type == "deployment_readiness")
    assert "deploy" not in release_job.request_text.casefold()


def test_archive_and_harvester_use_dedicated_tools(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    agent = CalyxAgentService()

    archive = agent.handle(actor="owner", request_text="Inspect archive readiness", use_provider=False)
    harvester = agent.handle(actor="owner", request_text="Inspect harvester readiness", use_provider=False)

    assert archive.tool_results[0].tool_id == "archive.readiness"
    assert harvester.tool_results[0].tool_id == "harvester.readiness"


def test_status_findings_are_owner_scoped(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())

    for owner in ("owner-a", "owner-b"):
        service.seed_overnight(owner=owner)
        job = service.claim(worker_id=f"worker-{owner}")
        assert job is not None
        token = job.lease_token
        assert token
        service.execute(job, worker_id=f"worker-{owner}", lease_token=token)

    owner_a_job_ids = {job.job_id for job in db.query(CalyxJob).filter(CalyxJob.owner == "owner-a")}
    status = service.status(owner="owner-a")
    assert status["findings"]
    assert {item["job_id"] for item in status["findings"]} <= owner_a_job_ids


def test_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CALYX_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("CALYX_ORCHESTRATOR_MODE", raising=False)
    assert enabled() is False
    monkeypatch.setenv("CALYX_ORCHESTRATOR_ENABLED", "true")
    monkeypatch.setenv("CALYX_ORCHESTRATOR_MODE", "preproduction")
    assert enabled() is True


def teardown_module() -> None:
    os.environ.pop("CALYX_ORCHESTRATOR_ENABLED", None)
    os.environ.pop("CALYX_ORCHESTRATOR_MODE", None)
