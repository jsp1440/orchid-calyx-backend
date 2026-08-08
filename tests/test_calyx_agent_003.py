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
    Base.metadata.create_all(engine, tables=[CalyxJob.__table__, CalyxFinding.__table__])
    return sessionmaker(bind=engine)()


def test_seed_overnight_is_durable_and_idempotent(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    first = service.seed_overnight(owner="owner")
    second = service.seed_overnight(owner="owner")
    assert len(first) == 9
    assert {job.job_id for job in first} == {job.job_id for job in second}
    assert db.query(CalyxJob).count() == 9
    assert {job.job_type for job in first}.issuperset(
        {"website_design_audit", "education_readiness"}
    )


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
    finding = db.query(CalyxFinding).one()
    assert finding.job_id == completed.job_id
    assert finding.provenance_json


def test_stale_worker_cannot_complete_after_reclaim(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    db = _session()
    service = CalyxOrchestrator(db, CalyxAgentService())
    service.seed_overnight(owner="owner")
    first = service.claim(worker_id="worker-1", lease_seconds=120)
    assert first is not None
    old_token = first.lease_token
    first.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    second = service.claim(worker_id="worker-2", lease_seconds=120)
    assert second is not None
    assert second.job_id == first.job_id
    assert second.lease_token != old_token
    try:
        service.execute(first, worker_id="worker-1", lease_token=old_token)
        raise AssertionError("stale lease should fail")
    except PermissionError as exc:
        assert str(exc) == "STALE_WORKER_LEASE"


def test_worker_is_disabled_without_preproduction_gate(monkeypatch):
    monkeypatch.delenv("CALYX_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("CALYX_ORCHESTRATOR_MODE", raising=False)
    assert enabled() is False
    monkeypatch.setenv("CALYX_ORCHESTRATOR_ENABLED", "true")
    monkeypatch.setenv("CALYX_ORCHESTRATOR_MODE", "production")
    assert enabled() is False
    monkeypatch.setenv("CALYX_ORCHESTRATOR_MODE", "preproduction")
    assert enabled() is True


def test_process_environment_is_not_modified():
    assert isinstance(os.environ, os._Environ)
