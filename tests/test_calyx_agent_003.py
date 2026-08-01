from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_agent.service import CalyxAgentService
from app.calyx_orchestrator.models import CalyxFinding, CalyxJob
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
