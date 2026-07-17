from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def configure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code-075")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "session-secret-075")
    monkeypatch.setenv("CALYX_API_KEY", "api-key-075")


def _login(client: TestClient) -> str:
    resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-075"},
    )
    assert resp.status_code == 200
    return resp.json()["token"]


def test_owner_executive_intelligence_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/executive-intelligence")
    assert resp.status_code == 401


def test_owner_executive_intelligence_returns_snapshot_when_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/executive-intelligence",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["build"] == "BUILD-075"
    assert body["section_id"] == "executive_intelligence"
    assert body["owner"] == "owner"
    assert "providers" in body
    assert "budgets" in body
    assert "recommendation_queue" in body
    assert "execution_history" in body
    assert "workflow_logs" in body
    assert "usage_ledger" in body
    assert "layout" in body
    assert "allowedActions" in body


def test_owner_executive_intelligence_snapshot_is_read_only_except_review(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/executive-intelligence",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert body["mode"] == "read_only_except_approval_reject"
    assert body["mutation_policy"]["default_mode"] == "read_only"
    assert body["mutation_policy"]["allowed_actions"] == ["approve_recommendation", "reject_recommendation"]
    assert "workflow_routing" in body["mutation_policy"]["blocked_actions"]


def test_owner_executive_intelligence_snapshot_includes_future_module_slots(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    layout = client.get(
        "/api/mission-control/owner/executive-intelligence",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["layout"]

    future_modules = {item["id"] for item in layout["future_modules"]}
    assert {
        "skas",
        "literature_acquisition",
        "source_registry",
        "harvesters",
        "research_agents",
        "knowledge_object_generation",
    } <= future_modules


def test_executive_session_includes_executive_intelligence_section(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    body = client.get("/api/mission-control/owner/executive-session").json()
    sections = {item["id"]: item for item in body["mission_control"]["sections"]}

    assert "executive_intelligence" in sections
    assert sections["executive_intelligence"]["endpoint"] == "/api/mission-control/owner/executive-intelligence"


def test_owner_eos_state_includes_executive_intelligence(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/eos-state",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert "executive_intelligence" in body
    assert body["executive_intelligence"]["section_id"] == "executive_intelligence"


def test_mission_control_executive_flow_includes_executive_intelligence_step(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    steps = client.get("/api/mission-control/executive-flow").json()["workflow_steps"]
    target = next((item for item in steps if item["section"] == "executive_intelligence_mission_control"), None)

    assert target is not None
    assert target["api_endpoint"] == "/api/mission-control/owner/executive-intelligence"


def test_owner_executive_intelligence_decision_endpoint_records_approval(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    def fake_decide(recommendation_id: int, decision: str, actor: str | None, notes: str | None):
        return {
            "id": recommendation_id,
            "status": "APPROVED",
            "decision_actor": actor,
            "decision_notes": notes,
            "title": "Review recommendation",
        }

    monkeypatch.setattr("app.routers.owner_operations.executive_intelligence_decide", fake_decide)
    resp = client.patch(
        "/api/mission-control/owner/executive-intelligence/recommendations/12",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "APPROVE", "notes": "Looks good"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-075"
    assert body["review_status"] == "decision_recorded"
    assert body["recommendation"]["status"] == "APPROVED"
    assert body["recommendation"]["decision_actor"] == "owner"


def test_owner_executive_intelligence_decision_endpoint_returns_404_for_missing_pending_item(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    monkeypatch.setattr("app.routers.owner_operations.executive_intelligence_decide", lambda *args, **kwargs: None)
    resp = client.patch(
        "/api/mission-control/owner/executive-intelligence/recommendations/12",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "REJECT"},
    )
    assert resp.status_code == 404


def test_kernel_registry_includes_build_075():
    from runtime.kernel_registry import KernelRegistryService

    registry = KernelRegistryService()
    build = next(item for item in registry.builds() if item.id == "build-075")
    assert "executive-intelligence-mission-control" in build.capabilities
    assert build.next_build == "BUILD-076"
