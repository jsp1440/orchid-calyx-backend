import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.missions.dependencies import get_mission_service
from app.missions.repositories import InMemoryMissionRepository, PostgresMissionRepository, json_safe_payload
from app.missions.routers import router, runtime_queue_router, templates_router
from app.missions.services import MissionService
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key


def mission_payload(**overrides: Any) -> dict[str, Any]:
    data = {
        "mission_key": "health-audit-1",
        "title": "Mission Control System Health Audit",
        "description": "Read-only health audit.",
        "mission_type": "system_health_check",
        "requested_by": "owner",
        "priority": 80,
        "maximum_runs": 1,
        "input_manifest": {},
        "allowed_actions": ["read_health"],
        "prohibited_actions": ["taxonomy_write", "external_api_call", "arbitrary_code"],
        "idempotency_key": "health-audit-1",
    }
    data.update(overrides)
    return data


@pytest.fixture
def repository() -> InMemoryMissionRepository:
    return InMemoryMissionRepository()


@pytest.fixture
def service(repository: InMemoryMissionRepository) -> MissionService:
    return MissionService(repository)


def test_mission_lifecycle_create_submit_approve_queue_execute_complete(service: MissionService):
    mission = service.create(mission_payload(), {"auth_type": "owner_session"})
    assert mission["state"] == "draft"
    assert service.submit(mission["mission_id"], "owner", "ready")["state"] == "awaiting_approval"
    assert service.approve(mission["mission_id"], "owner", "approved", "approval-079")["state"] == "approved"
    assert service.queue(mission["mission_id"], "owner", "queue")["state"] == "queued"

    result = service.execute_cycle("worker-1")

    assert result["status"] == "completed"
    completed = service.get(mission["mission_id"])
    assert completed["state"] == "completed"
    assert completed["output_manifest"]["canonical_graph_mutated"] is False
    assert completed["output_manifest"]["taxonomy_mutated"] is False
    assert service.jobs(mission["mission_id"])[0]["state"] == "succeeded"
    assert service.events(mission["mission_id"])


def test_pause_resume_cancel_reject_retry_and_transition_guards(service: MissionService):
    mission = service.create(mission_payload(mission_key="pause", idempotency_key="pause"), {})
    service.submit(mission["mission_id"], "owner", "submit")
    with pytest.raises(ValueError, match="INVALID_MISSION_TRANSITION"):
        service.queue(mission["mission_id"], "owner", "too early")
    service.reject(mission["mission_id"], "owner", "not now")
    assert service.get(mission["mission_id"])["state"] == "blocked"

    second = service.create(mission_payload(mission_key="cancel", idempotency_key="cancel"), {})
    service.submit(second["mission_id"], "owner", "submit")
    service.approve(second["mission_id"], "owner", "approve", "approval")
    service.pause(second["mission_id"], "owner", "pause")
    assert service.resume(second["mission_id"], "owner", "resume")["state"] == "approved"
    assert service.cancel(second["mission_id"], "owner", "cancel")["state"] == "cancelled"


def test_high_risk_publication_mission_requires_explicit_authority(service: MissionService):
    mission = service.create(mission_payload(mission_key="pub", idempotency_key="pub", mission_type="controlled_publication"), {})
    service.submit(mission["mission_id"], "owner", "submit")

    with pytest.raises(ValueError, match="HIGH_RISK_APPROVAL_REFERENCE_REQUIRED"):
        service.approve(mission["mission_id"], "owner", "approve", None)
    with pytest.raises(ValueError, match="PUBLICATION_AUTHORITY_REQUIRED"):
        service.approve(mission["mission_id"], "owner", "approve", "approval")
    assert service.approve(mission["mission_id"], "owner", "approve", "approval", "publisher")["state"] == "approved"


def test_forbidden_payloads_reject_arbitrary_execution_paths(service: MissionService):
    with pytest.raises(ValueError, match="FORBIDDEN_MISSION_PAYLOAD"):
        service.create(mission_payload(input_manifest={"shell": "rm -rf /"}), {})
    with pytest.raises(ValueError, match="FORBIDDEN_MISSION_PAYLOAD"):
        service.create(mission_payload(mission_key="url", idempotency_key="url", input_manifest={"url": "https://example.com"}), {})


def test_idempotent_enqueue_and_priority_ordering(service: MissionService):
    low = service.create(mission_payload(mission_key="low", idempotency_key="low", priority=10), {})
    high = service.create(mission_payload(mission_key="high", idempotency_key="high", priority=90), {})
    for mission in (low, high):
        service.submit(mission["mission_id"], "owner", "submit")
        service.approve(mission["mission_id"], "owner", "approve", "approval")
        service.queue(mission["mission_id"], "owner", "queue")
        with pytest.raises(ValueError, match="INVALID_MISSION_TRANSITION"):
            service.queue(mission["mission_id"], "owner", "queue again")

    claimed = service.repository.claim_job("worker-priority")

    assert claimed["mission_id"] == high["mission_id"]
    assert service.repository.queue_depth() == 1


def test_lease_recovery_retry_and_dead_letter(service: MissionService):
    mission = service.create(mission_payload(mission_key="lease", idempotency_key="lease", mission_type="intake_batch_review"), {})
    service.submit(mission["mission_id"], "owner", "submit")
    service.approve(mission["mission_id"], "owner", "approve", "approval")
    service.queue(mission["mission_id"], "owner", "queue")

    claimed = service.repository.claim_job("crashed-worker")
    assert claimed["state"] == "claimed"
    assert service.repository.recover_expired_leases("recovery-worker") == 1

    retry = service.create(mission_payload(mission_key="blocked-handler", idempotency_key="blocked-handler", mission_type="intake_batch_review"), {})
    service.submit(retry["mission_id"], "owner", "submit")
    service.approve(retry["mission_id"], "owner", "approve", "approval")
    service.queue(retry["mission_id"], "owner", "queue")
    first = service.execute_cycle("worker-fail")
    second = service.execute_cycle("worker-fail")

    assert first["status"] == "failed"
    assert second["status"] == "failed"
    assert service.dead_letters()
    assert service.get(mission["mission_id"])["state"] == "failed"


def test_dead_letter_payload_is_json_safe_for_postgres_datetime_rows():
    payload = json_safe_payload({"job_id": 1, "claimed_at": datetime(2026, 7, 19, tzinfo=timezone.utc)})

    assert payload["claimed_at"] == "2026-07-19 00:00:00+00:00"
    assert json.loads(json.dumps(payload))["job_id"] == 1


def test_runtime_enqueue_cycle_has_no_jobs_behavior(service: MissionService):
    assert service.enqueue_cycle("worker")["status"] == "no_jobs"
    assert service.execute_cycle("worker")["status"] == "no_jobs"
    assert service.queue_status()["authorization_readiness"] == "owner_session_or_api_key_required"


def test_api_routes_are_authenticated_and_execute_safe_mission(repository: InMemoryMissionRepository):
    app = FastAPI()
    app.include_router(router)
    app.include_router(templates_router)
    app.include_router(runtime_queue_router)
    client = TestClient(app)

    assert client.post("/api/missions", json=mission_payload()).status_code == 401

    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner", "auth_type": "owner_session"}
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    app.dependency_overrides[get_mission_service] = lambda: MissionService(repository)
    client = TestClient(app)

    created = client.post("/api/missions", json=mission_payload()).json()
    mission_id = created["mission_id"]
    assert client.post(f"/api/missions/{mission_id}/submit", json={"actor": "owner", "reason": "submit"}).status_code == 200
    assert client.post(f"/api/missions/{mission_id}/approve", json={"actor": "owner", "reason": "approve", "approval_reference": "approval"}).status_code == 200
    assert client.post(f"/api/missions/{mission_id}/queue", json={"actor": "owner", "reason": "queue"}).status_code == 200
    assert client.post("/api/runtime/cycle", json={"worker_id": "api-worker", "limit": 1}).json()["status"] == "completed"
    assert client.get(f"/api/missions/{mission_id}/jobs").json()["items"][0]["state"] == "succeeded"
    assert client.get("/api/mission-templates").json()["items"]
    assert client.get("/api/runtime/queue").json()["total_missions"] == 1


def test_migration_is_additive_and_enforces_state_and_audit_protection():
    sql = Path("migrations/079_controlled_mission_orchestration.sql").read_text(encoding="utf-8").lower()

    assert "create schema if not exists oc_missions" in sql
    assert sql.count("create table if not exists oc_missions.") >= 8
    assert "mission_events_append_only" in sql
    assert "missions_state_transition_valid" in sql
    assert "drop table" not in sql
    assert "alter table oc_graph" not in sql
    assert "alter table oc_taxonomy" not in sql
    assert "delete from oc_taxonomy" not in sql


def test_postgres_repository_uses_skip_locked_and_does_not_define_external_execution():
    source = Path("app/missions/repositories.py").read_text(encoding="utf-8").lower()
    service_source = Path("app/missions/services.py").read_text(encoding="utf-8").lower()

    assert "for update skip locked" in source
    assert "dead_letter_jobs" in source
    assert "import subprocess" not in service_source
    assert "requests." not in service_source
    assert "httpx" not in service_source
