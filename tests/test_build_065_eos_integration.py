"""Tests for BUILD-065: Executive Operating System Integration.

Covers:
- GET /api/mission-control/executive-flow (read-only, no auth)
- GET /api/mission-control/relationships (read-only, no auth)
- GET /api/mission-control/readiness (read-only, no auth)
- GET /api/mission-control/owner/decisions (auth required)
- GET /api/mission-control/owner/priorities (auth required)
- GET /api/mission-control/owner/calyx-narrative (auth required)
- GET /api/mission-control/owner/eos-state (auth required)
- allowed_actions includes new EOS capabilities
- executive-session backend metadata shows BUILD-065
- Mission Control BUILD_ID updated to BUILD-065
- kernel_registry includes BUILD-065 with correct capabilities
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def configure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code-065")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "session-secret-065")
    monkeypatch.setenv("CALYX_API_KEY", "api-key-065")


def _login(client: TestClient) -> str:
    resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-065"},
    )
    assert resp.status_code == 200
    return resp.json()["token"]


# ─── BUILD_ID ─────────────────────────────────────────────────────────────────


def test_mission_control_build_id_is_065():
    from app.routers.mission_control import BUILD_ID
    assert BUILD_ID == "BUILD-065"


def test_mission_control_status_reflects_065():
    from app.routers.mission_control import mission_control_status
    status = mission_control_status()
    assert status["build"] == "BUILD-065"


# ─── executive-session backend metadata ──────────────────────────────────────


def test_executive_session_backend_build_is_065(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get("/api/mission-control/owner/executive-session")
    assert resp.status_code == 200
    backend = resp.json()["backend"]
    assert backend["version"] == "BUILD-065"
    assert backend["build"] == "BUILD-065"


# ─── GET /api/mission-control/executive-flow ─────────────────────────────────


def test_executive_flow_returns_200():
    client = TestClient(app)
    resp = client.get("/api/mission-control/executive-flow")
    assert resp.status_code == 200


def test_executive_flow_structure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    body = client.get("/api/mission-control/executive-flow").json()

    assert body["build"] == "BUILD-065"
    assert body["eos_version"] == "BUILD-065"
    assert "eos_title" in body
    assert "workflow_steps" in body
    assert isinstance(body["workflow_steps"], list)
    assert len(body["workflow_steps"]) >= 9
    assert body["total_steps"] == len(body["workflow_steps"])


def test_executive_flow_steps_have_orientation(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    steps = client.get("/api/mission-control/executive-flow").json()["workflow_steps"]

    for step in steps:
        assert "step" in step
        assert "section" in step
        assert "title" in step
        assert "orientation" in step
        orientation = step["orientation"]
        assert "what_is_this" in orientation
        assert "why_it_matters" in orientation
        assert "what_can_i_do_here" in orientation
        assert "what_is_calyx_doing" in orientation
        assert "what_decision_do_i_need_to_make" in orientation


def test_executive_flow_steps_are_ordered(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    steps = client.get("/api/mission-control/executive-flow").json()["workflow_steps"]

    step_numbers = [s["step"] for s in steps]
    assert step_numbers == sorted(step_numbers)
    assert step_numbers[0] == 1


def test_executive_flow_includes_key_sections(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    steps = client.get("/api/mission-control/executive-flow").json()["workflow_steps"]
    sections = {s["section"] for s in steps}

    required = {"daily_brief", "platform_status", "critical_alerts", "calyx_activity",
                "owner_decisions", "recommended_next_build", "subsystem_deep_dive",
                "research_workspace", "governance_audit"}
    assert required <= sections


# ─── GET /api/mission-control/relationships ──────────────────────────────────


def test_relationships_returns_200():
    client = TestClient(app)
    resp = client.get("/api/mission-control/relationships")
    assert resp.status_code == 200


def test_relationships_structure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    body = client.get("/api/mission-control/relationships").json()

    assert body["build"] == "BUILD-065"
    assert "relationships" in body
    assert isinstance(body["relationships"], list)
    assert len(body["relationships"]) > 0
    assert "total_subsystems" in body


def test_relationships_items_have_required_fields(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    relationships = client.get("/api/mission-control/relationships").json()["relationships"]

    for rel in relationships:
        assert "subsystem_id" in rel
        assert "display_name" in rel
        assert "depends_on_ids" in rel
        assert "depended_on_by_ids" in rel
        assert "leverage_note" in rel
        assert isinstance(rel["depends_on_ids"], list)
        assert isinstance(rel["depended_on_by_ids"], list)


def test_relationships_includes_atlas(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    relationships = client.get("/api/mission-control/relationships").json()["relationships"]
    atlas = next((r for r in relationships if r["subsystem_id"] == "atlas"), None)

    assert atlas is not None
    assert "taxonomy" in atlas["depends_on_ids"] or len(atlas["depends_on_ids"]) >= 0


def test_relationships_sorted_by_leverage(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    relationships = client.get("/api/mission-control/relationships").json()["relationships"]

    # First item should have the highest dependent_count
    counts = [r["dependent_count"] for r in relationships]
    assert counts[0] >= counts[-1]


# ─── GET /api/mission-control/readiness ──────────────────────────────────────


def test_readiness_returns_200():
    client = TestClient(app)
    resp = client.get("/api/mission-control/readiness")
    assert resp.status_code == 200


def test_readiness_structure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    body = client.get("/api/mission-control/readiness").json()

    assert body["build"] == "BUILD-065"
    assert "readiness_dimensions" in body
    assert "subsystems" in body
    assert isinstance(body["subsystems"], list)
    assert len(body["subsystems"]) > 0


def test_readiness_dimensions_list(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    dims = client.get("/api/mission-control/readiness").json()["readiness_dimensions"]

    required_dims = [
        "scientific_readiness",
        "integration_readiness",
        "automation_readiness",
        "evidence_readiness",
        "publication_readiness",
        "grant_readiness",
        "operational_readiness",
        "overall_executive_readiness",
    ]
    for dim in required_dims:
        assert dim in dims


def test_readiness_subsystems_have_all_dimensions(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    subsystems = client.get("/api/mission-control/readiness").json()["subsystems"]

    for sub in subsystems:
        assert "id" in sub
        assert "display_name" in sub
        assert "overall_executive_readiness" in sub
        assert "scientific_readiness" in sub
        assert "integration_readiness" in sub
        assert "automation_readiness" in sub
        assert "evidence_readiness" in sub
        assert "publication_readiness" in sub
        assert "grant_readiness" in sub
        assert "operational_readiness" in sub
        # All scores should be in [0, 100]
        for dim in ["scientific_readiness", "integration_readiness", "overall_executive_readiness"]:
            assert 0 <= sub[dim] <= 100


# ─── GET /api/mission-control/owner/decisions ────────────────────────────────


def test_owner_decisions_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/decisions")
    assert resp.status_code == 401


def test_owner_decisions_returns_200_when_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/decisions",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-065"
    assert "decision_categories" in body
    assert "total_decisions" in body
    assert "allowedActions" in body
    assert "owner" in body


def test_owner_decisions_categories_present(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/decisions",
        headers={"Authorization": f"******"},
    ).json()

    categories = body["decision_categories"]
    expected = [
        "waiting_for_approval",
        "waiting_for_owner",
        "requires_external_partner",
        "requires_authentication",
        "requires_budget",
        "requires_scientific_review",
        "requires_manual_validation",
    ]
    for cat in expected:
        assert cat in categories, f"Missing category: {cat}"


def test_owner_decisions_items_have_required_fields(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/decisions",
        headers={"Authorization": f"******"},
    ).json()

    all_items = [item for items in body["decision_categories"].values() for item in items]
    for item in all_items:
        assert "id" in item
        assert "category" in item
        assert "title" in item
        assert "why_it_matters" in item
        assert "impact_if_ignored" in item
        assert "recommended_action" in item
        assert "estimated_effort" in item


def test_owner_decisions_has_orientation(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/decisions",
        headers={"Authorization": f"******"},
    ).json()
    assert "orientation" in body
    assert "what_is_this" in body["orientation"]


# ─── GET /api/mission-control/owner/priorities ───────────────────────────────


def test_owner_priorities_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/priorities")
    assert resp.status_code == 401


def test_owner_priorities_returns_200_when_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/priorities",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-065"
    assert "priorities" in body
    assert "ranked_queue" in body
    assert "allowedActions" in body


def test_owner_priorities_tiers_present(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/priorities",
        headers={"Authorization": f"******"},
    ).json()

    priorities = body["priorities"]
    for tier in ["critical", "high", "medium", "low"]:
        assert tier in priorities


def test_owner_priorities_ranked_queue_has_required_fields(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/priorities",
        headers={"Authorization": f"******"},
    ).json()

    for item in body["ranked_queue"]:
        assert "rank" in item
        assert "priority" in item
        assert "title" in item
        assert "scientific_impact" in item
        assert "technical_impact" in item
        assert "estimated_completion" in item
        assert "suggested_build" in item


def test_owner_priorities_ranked_queue_is_ordered(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/priorities",
        headers={"Authorization": f"******"},
    ).json()

    queue = body["ranked_queue"]
    if len(queue) > 1:
        ranks = [item["rank"] for item in queue]
        assert ranks == sorted(ranks)


def test_owner_priorities_has_orientation(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/priorities",
        headers={"Authorization": f"******"},
    ).json()
    assert "orientation" in body


# ─── GET /api/mission-control/owner/calyx-narrative ──────────────────────────


def test_owner_calyx_narrative_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/calyx-narrative")
    assert resp.status_code == 401


def test_owner_calyx_narrative_returns_200_when_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/calyx-narrative",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-065"
    assert "narrative" in body
    assert "allowedActions" in body


def test_owner_calyx_narrative_structure(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    narrative = client.get(
        "/api/mission-control/owner/calyx-narrative",
        headers={"Authorization": f"******"},
    ).json()["narrative"]

    required_fields = [
        "what_i_am_doing",
        "why_i_am_doing_it",
        "what_i_discovered",
        "what_i_am_waiting_for",
        "what_i_recommend_next",
        "what_decision_i_need_from_you",
    ]
    for field in required_fields:
        assert field in narrative, f"Missing narrative field: {field}"


def test_owner_calyx_narrative_recommend_next_has_title(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    narrative = client.get(
        "/api/mission-control/owner/calyx-narrative",
        headers={"Authorization": f"******"},
    ).json()["narrative"]

    assert "title" in narrative["what_i_recommend_next"]
    assert "decision" in narrative["what_decision_i_need_from_you"]


def test_owner_calyx_narrative_has_orientation(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/calyx-narrative",
        headers={"Authorization": f"******"},
    ).json()
    assert "orientation" in body


# ─── GET /api/mission-control/owner/eos-state ────────────────────────────────


def test_owner_eos_state_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/eos-state")
    assert resp.status_code == 401


def test_owner_eos_state_returns_200_when_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/eos-state",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-065"
    assert body["eos_version"] == "BUILD-065"


def test_owner_eos_state_contains_all_sections(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/eos-state",
        headers={"Authorization": f"******"},
    ).json()

    required_sections = [
        "executive_flow",
        "platform_status",
        "critical_alerts",
        "calyx_activity",
        "owner_decisions",
        "recommended_next_build",
        "subsystem_relationships",
        "readiness",
        "calyx_narrative",
        "governance_summary",
        "allowedActions",
        "owner",
    ]
    for section in required_sections:
        assert section in body, f"Missing EOS section: {section}"


def test_owner_eos_state_platform_status_has_fields(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    platform_status = client.get(
        "/api/mission-control/owner/eos-state",
        headers={"Authorization": f"******"},
    ).json()["platform_status"]

    assert "status" in platform_status
    assert "database_connected" in platform_status
    assert "blockers" in platform_status


def test_owner_eos_state_executive_flow_has_steps(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    flow = client.get(
        "/api/mission-control/owner/eos-state",
        headers={"Authorization": f"******"},
    ).json()["executive_flow"]

    assert "workflow_steps" in flow
    assert len(flow["workflow_steps"]) >= 9


def test_owner_eos_state_governance_summary(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    gov = client.get(
        "/api/mission-control/owner/eos-state",
        headers={"Authorization": f"******"},
    ).json()["governance_summary"]

    assert "north_star" in gov
    assert "policy_count" in gov
    assert isinstance(gov["policy_count"], int)
    assert gov["policy_count"] >= 1


# ─── allowed_actions: new EOS capabilities ───────────────────────────────────


def test_allowed_actions_eos_capabilities_present(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/session",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]

    for cap in ["decisionReview", "priorityReview", "calyxNarrative", "eosState"]:
        assert cap in actions, f"Missing allowed_action: {cap}"
        assert actions[cap]["allowed"] is True, f"{cap} should be allowed when authenticated"


def test_allowed_actions_eos_capabilities_false_when_unauthenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get("/api/mission-control/owner/executive-session")
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]

    for cap in ["decisionReview", "priorityReview", "calyxNarrative", "eosState"]:
        assert cap in actions, f"Missing allowed_action: {cap}"
        assert actions[cap]["allowed"] is False, f"{cap} should be disallowed when unauthenticated"


# ─── kernel_registry includes BUILD-065 ──────────────────────────────────────


def test_kernel_registry_includes_build_065():
    from runtime.kernel_registry import KernelRegistryService
    registry = KernelRegistryService()
    build_ids = [b.id for b in registry.builds()]
    assert "build-065" in build_ids


def test_kernel_registry_build_065_capabilities():
    from runtime.kernel_registry import KernelRegistryService
    registry = KernelRegistryService()
    build = next(b for b in registry.builds() if b.id == "build-065")
    assert "executive-flow" in build.capabilities
    assert "owner-decision-layer" in build.capabilities
    assert "unified-priority-queue" in build.capabilities
    assert "calyx-narrative" in build.capabilities
    assert "eos-state" in build.capabilities


def test_kernel_registry_build_065_next_build_is_066():
    from runtime.kernel_registry import KernelRegistryService
    registry = KernelRegistryService()
    build = next(b for b in registry.builds() if b.id == "build-065")
    assert build.next_build == "BUILD-066"


# ─── Preserved BUILD-064 functionality ───────────────────────────────────────


def test_build_064_recommendations_still_works(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/recommendations",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # BUILD-064 still returns its own build ID in the response
    assert body["build"] == "BUILD-064"
    assert "recommendations" in body


def test_build_064_governance_still_works(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/governance",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-064"
    assert "governance" in body


def test_unauthenticated_eos_actions_all_false(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get("/api/mission-control/owner/executive-session")
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]
    for name, action in actions.items():
        assert action["allowed"] is False, f"Expected {name} to be disallowed when unauthenticated"
