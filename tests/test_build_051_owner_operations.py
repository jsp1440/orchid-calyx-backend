from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.health import router as health_router
from app.routers.harvesters import router as harvesters_router
from app.routers.owner_operations import MEMORY


def client() -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(harvesters_router)
    return TestClient(app)


def configure_owner(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-session-secret")
    for rows in MEMORY.values():
        rows.clear()


def owner_token(api: TestClient) -> str:
    response = api.post("/api/mission-control/owner/session", json={"access_code": "owner-code", "owner": "jeff"})
    assert response.status_code == 200
    body = response.json()
    assert "owner-code" not in response.text
    assert "test-session-secret" not in response.text
    return body["token"]


def test_owner_session_fails_closed_without_configuration(monkeypatch):
    monkeypatch.delenv("CALYX_OWNER_ACCESS_CODE", raising=False)
    monkeypatch.delenv("CALYX_OWNER_SESSION_SECRET", raising=False)
    response = client().post("/api/mission-control/owner/session", json={"access_code": "owner-code"})
    assert response.status_code == 503


def test_invalid_owner_code_rejected(monkeypatch):
    configure_owner(monkeypatch)
    response = client().post("/api/mission-control/owner/session", json={"access_code": "wrong"})
    assert response.status_code == 401


def test_authenticated_permissions_and_unauthenticated_write_rejection(monkeypatch):
    configure_owner(monkeypatch)
    api = client()
    denied = api.post("/api/mission-control/owner/commands", json={"command": "Show operations queue"})
    assert denied.status_code == 401
    token = owner_token(api)
    allowed = api.get("/api/mission-control/owner/permissions", headers={"Authorization": f"Bearer {token}"})
    assert allowed.status_code == 200
    assert allowed.json()["allowedActions"]["submitCommand"]["allowed"] is True


def test_persisted_owner_session_can_be_validated(monkeypatch):
    configure_owner(monkeypatch)
    api = client()
    token = owner_token(api)
    response = api.get("/api/mission-control/owner/session", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authenticated"
    assert body["owner"] == "jeff"
    assert body["auth_type"] == "owner_session"
    assert body["expires_at"]
    assert body["allowedActions"]["approveQueueItem"]["allowed"] is True
    assert body["allowedActions"]["approveQueueItem"]["requiresConfirmation"] is True
    assert body["allowedActions"]["promoteBrainKnowledge"]["allowed"] is True
    assert body["allowedActions"]["promoteBrainKnowledge"]["state"] == "owner_authorized_action"


def test_source_briefing_persists_and_routes_grants(monkeypatch):
    configure_owner(monkeypatch)
    api = client()
    token = owner_token(api)
    response = api.post(
        "/api/mission-control/owner/source-briefings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source": "Twin Daily Brief",
            "source_date": "2026-07-10",
            "raw_text": "Grant: Orchid habitat restoration\nDeadline: 2026-08-01\n\nPartner: University lab collaboration",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "saved"
    assert len(body["items"]) >= 2
    listed = api.get("/api/mission-control/owner/intelligence", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert listed.json()["grants"]
    assert listed.json()["partnerships"]


def test_local_import_deduplicates(monkeypatch):
    configure_owner(monkeypatch)
    api = client()
    token = owner_token(api)
    payload = {"records": [{"title": "A", "summary": "Same item", "source_excerpt": "same"}]}
    first = api.post("/api/mission-control/owner/intelligence/import-local", headers={"Authorization": f"Bearer {token}"}, json=payload)
    second = api.post("/api/mission-control/owner/intelligence/import-local", headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert first.json()["imported"]
    assert second.json()["skipped_duplicates"] == 1


def test_audit_command_queue_research_and_packet(monkeypatch):
    configure_owner(monkeypatch)
    api = client()
    token = owner_token(api)
    headers = {"Authorization": f"Bearer {token}"}
    audit = api.post("/api/mission-control/owner/audits", headers=headers, json={"audit_type": "overall", "output_format": "markdown"})
    assert audit.status_code == 200
    assert "Record Counts" in audit.json()["audit"]["content"]
    command = api.post("/api/mission-control/owner/commands", headers=headers, json={"command": "Show missing relationships"})
    assert command.status_code == 200
    assert command.json()["command"]["id"].startswith("CMD-")
    queue = api.get("/api/mission-control/owner/operations-queue", headers=headers)
    assert queue.status_code == 200
    assert queue.json()["items"]
    research = api.post(
        "/api/mission-control/owner/research-requests",
        headers=headers,
        json={"title": "Lycaste comparison", "research_question": "Compare Lycaste habitat evidence."},
    )
    assert research.status_code == 200
    packet = api.post(
        "/api/mission-control/owner/partnership-packets",
        headers=headers,
        json={"organization_name": "GBIF", "partner_type": "data federation", "output_format": "markdown"},
    )
    assert packet.status_code == 200
    assert "GBIF" in packet.json()["packet"]["content"]


def test_harvester_owner_session_allows_safe_mutation(monkeypatch):
    configure_owner(monkeypatch)
    api = client()
    token = owner_token(api)
    unauthorized = client().post("/api/harvesters/gbif/pause")
    assert unauthorized.status_code == 401
    authorized = api.post("/api/harvesters/gbif/pause", headers={"Authorization": f"Bearer {token}"})
    assert authorized.status_code == 200
    assert authorized.json()["harvester"]["provenance"]["last_actor"] == "jeff"
