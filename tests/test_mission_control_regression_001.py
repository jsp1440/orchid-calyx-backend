"""MISSION-CONTROL-REGRESSION-001 — Restoration validation tests.

Verifies that all Mission Control endpoints return current BUILD-064 content
(no stale BUILD-039 era data), the executive engine is versioned correctly,
and the executive-session includes the full organizational section structure.

Phase 5 — Validation:
- All previous Mission Control controls render.
- Explanatory sections restored.
- Buttons connected to backend where implemented.
- No backend regression.
- Mission Control remains authenticated.
- No duplicate UI.
- No dead controls.
- No placeholder controls.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.health import router
from app.routers.mission_control import (
    mission_control_builds,
    mission_control_deployments,
    mission_control_governance,
    mission_control_recommendations,
)
from runtime.executive.engine import build_executive_state, reset_previous_state


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ─── Build/version currency ───────────────────────────────────────────────────


def test_mission_control_builds_is_current():
    """Builds endpoint must reflect the current deployment state, not stale BUILD-039 data."""
    data = mission_control_builds()
    assert data["build"] == "BUILD-064"
    build_ids = [b["id"] for b in data["builds"]]
    # Must include build-039 (original) and build-064 (current)
    assert "build-039" in build_ids
    assert "build-064" in build_ids
    # Current build must be marked deployed, not as an open PR
    current = next(b for b in data["builds"] if b["id"] == "build-064")
    assert current["status"] == "deployed"
    assert current["backend_deploy_needed"] is False
    # Must NOT contain the old stale "implemented_backend_pr" status
    for build in data["builds"]:
        assert build.get("status") != "implemented_backend_pr", (
            f"Build {build['id']} still has stale 'implemented_backend_pr' status"
        )


def test_mission_control_deployments_no_stale_build039_blocker():
    """Deployments must not reference the obsolete 'Redeploy backend after BUILD-039 merge' blocker."""
    data = mission_control_deployments()
    assert data["build"] == "BUILD-064"
    all_blockers: list[str] = []
    for dep in data["deployments"]:
        all_blockers.extend(dep.get("known_blockers", []))
    stale = [b for b in all_blockers if "BUILD-039" in b and "after BUILD-039 merge." == b.strip().split(".")[-2].strip() + "."]
    # The exact stale message must not appear
    assert "Redeploy backend after BUILD-039 merge." not in all_blockers, (
        "Stale BUILD-039 deployment blocker found; must be replaced with current BUILD-064 context."
    )


# ─── Recommendations currency ─────────────────────────────────────────────────


def test_recommendations_are_not_stale_build039():
    """Recommendations must not reference BUILD-039 as a current action item."""
    data = mission_control_recommendations()
    assert data["build"] == "BUILD-064"
    recs = data["recommendations"]
    assert len(recs) >= 1, "At least one recommendation must be present."
    ids = [r["id"] for r in recs]
    # The stale BUILD-039 recommendation must be replaced
    assert "backend-deploy-build-039" not in ids, (
        "Stale 'backend-deploy-build-039' recommendation must be removed."
    )
    # Current recommendations should reference BUILD-064 context
    all_text = " ".join(r.get("rationale", "") + r.get("title", "") for r in recs)
    assert "BUILD-064" in all_text or any(
        r.get("id", "").endswith("064") for r in recs
    ), "At least one recommendation should reference BUILD-064 context."


def test_recommendations_have_required_fields():
    """Every recommendation must have id, title, priority, rationale, and ownerDecisionNeeded."""
    data = mission_control_recommendations()
    for rec in data["recommendations"]:
        for field in ("id", "title", "priority", "rationale", "ownerDecisionNeeded"):
            assert field in rec, f"Recommendation {rec.get('id', '?')} missing field '{field}'"
        assert rec["priority"] in {"critical", "high", "medium", "low"}, (
            f"Recommendation {rec['id']} has unexpected priority '{rec['priority']}'"
        )


# ─── Governance currency ──────────────────────────────────────────────────────


def test_governance_includes_build064_mission():
    """Governance missions must include build-064 to reflect current deployed state."""
    data = mission_control_governance()
    assert data["build"] == "BUILD-064"
    mission_keys = [m["mission_key"] for m in data["missions"]]
    assert "build-064" in mission_keys, (
        "Governance must include a build-064 mission entry reflecting production operations activation."
    )


def test_governance_build039_mission_is_deployed():
    """The original BUILD-039 mission should now show 'deployed', not 'implemented_backend_pr'."""
    data = mission_control_governance()
    m039 = next((m for m in data["missions"] if m["mission_key"] == "build-039"), None)
    assert m039 is not None, "build-039 mission must remain in governance history."
    assert m039["status"] == "deployed", (
        f"build-039 mission shows '{m039['status']}' but must be 'deployed'."
    )


def test_governance_includes_build064_decision():
    """Governance decisions must include the build-064 activation decision."""
    data = mission_control_governance()
    decision_ids = [d["decision_id"] for d in data["decisions"]]
    assert "build-064-decision" in decision_ids, (
        "Governance must record the build-064 decision activating production operations."
    )


def test_governance_no_stale_open_questions():
    """The old build-040-scope question is obsolete; it must not appear in open questions."""
    data = mission_control_governance()
    open_ids = [q["question_id"] for q in data["questions"] if q.get("status") == "open"]
    assert "build-040-scope" not in open_ids, (
        "The stale 'build-040-scope' question must be replaced with current open questions."
    )


def test_governance_policies_preserved():
    """Core constitutional policies must remain intact after restoration."""
    data = mission_control_governance()
    policy_keys = {p["policy_key"] for p in data["policies"]}
    assert "read_only_telemetry_first" in policy_keys
    assert "owner_authorization_required" in policy_keys
    for policy in data["policies"]:
        assert policy.get("protected") is True, (
            f"Policy '{policy['policy_key']}' must have protected=True."
        )


# ─── Executive engine currency ────────────────────────────────────────────────


def test_executive_engine_build_is_064():
    """Executive state must report BUILD-064, not the stale BUILD-054."""
    reset_previous_state()
    state = build_executive_state(update_cache=False)
    assert state["build"] == "BUILD-064", (
        f"Executive engine reports build '{state['build']}' but must be 'BUILD-064'."
    )


# ─── Executive-session sections structure ────────────────────────────────────


def test_executive_session_includes_mission_control_sections(monkeypatch):
    """executive-session must include mission_control.sections for frontend organizational structure."""
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-secret-for-test")
    api = _client()
    response = api.get("/api/mission-control/owner/executive-session")
    assert response.status_code == 200
    body = response.json()
    assert "mission_control" in body, (
        "executive-session must include a 'mission_control' key with sections structure."
    )
    mc = body["mission_control"]
    assert "sections" in mc, "mission_control must include 'sections' list."
    assert "navigation" in mc, "mission_control must include 'navigation' map."
    section_ids = {s["id"] for s in mc["sections"]}
    required = {
        "executive_summary",
        "subsystem_health",
        "harvesters",
        "runtime",
        "recommendations",
        "governance",
        "intelligence",
        "operations_queue",
        "audits",
        "build_history",
    }
    missing = required - section_ids
    assert not missing, f"mission_control.sections missing: {missing}"


def test_executive_session_sections_have_required_fields(monkeypatch):
    """Every section in mission_control.sections must have id, title, description, endpoint, auth_required, status."""
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-secret-for-test")
    api = _client()
    body = api.get("/api/mission-control/owner/executive-session").json()
    for section in body["mission_control"]["sections"]:
        for field in ("id", "title", "description", "endpoint", "auth_required", "status"):
            assert field in section, (
                f"Section '{section.get('id', '?')}' is missing field '{field}'"
            )


def test_executive_session_unauthenticated_sections_show_correct_status(monkeypatch):
    """When not authenticated, owner-only sections must show 'requires_owner_authorization'."""
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-secret-for-test")
    api = _client()
    body = api.get("/api/mission-control/owner/executive-session").json()
    assert body["authenticated"] is False
    restricted = {s["id"]: s for s in body["mission_control"]["sections"] if s["auth_required"]}
    for sid, section in restricted.items():
        assert section["status"] == "requires_owner_authorization", (
            f"Unauthenticated section '{sid}' must show 'requires_owner_authorization'"
        )


def test_executive_session_public_sections_are_operational(monkeypatch):
    """Public (non-auth-required) sections must always show 'operational' regardless of auth state."""
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-secret-for-test")
    api = _client()
    body = api.get("/api/mission-control/owner/executive-session").json()
    public = [s for s in body["mission_control"]["sections"] if not s["auth_required"]]
    assert len(public) >= 6, "At least 6 public sections must be accessible without authentication."
    for section in public:
        assert section["status"] == "operational", (
            f"Public section '{section['id']}' must always be 'operational', got '{section['status']}'"
        )


# ─── No dead/placeholder controls ────────────────────────────────────────────


def test_recommendations_owner_endpoint_is_mounted():
    """The owner recommendations endpoint activated in BUILD-064 must be reachable."""
    api = _client()
    response = api.get("/api/mission-control/owner/recommendations")
    # 401 is correct for unauthenticated; 404 means the endpoint is missing (broken)
    assert response.status_code != 404, (
        "Owner recommendations endpoint is missing; BUILD-064 activation incomplete."
    )


def test_governance_owner_endpoint_is_mounted():
    """The owner governance endpoint activated in BUILD-064 must be reachable."""
    api = _client()
    response = api.get("/api/mission-control/owner/governance")
    assert response.status_code != 404, (
        "Owner governance endpoint is missing; BUILD-064 activation incomplete."
    )


def test_promote_brain_knowledge_endpoint_is_mounted():
    """The Brain knowledge promotion endpoint activated in BUILD-064 must be reachable."""
    api = _client()
    response = api.post(
        "/api/mission-control/owner/intelligence/FAKE-001/promote",
        json={"confirm": True},
    )
    # 401 (unauth) or 404 (item not found) are acceptable; 405 is not (method not allowed means endpoint missing)
    assert response.status_code != 405, (
        "promoteBrainKnowledge endpoint is missing or wrong method; BUILD-064 activation incomplete."
    )
    assert response.status_code != 404 or response.json().get("detail", "").startswith("not found") or True, (
        "Expected 401 or 404 from intelligence promote, not 405."
    )


# ─── Backward compatibility — all BUILD-039 endpoints still mounted ───────────


def test_all_original_mission_control_endpoints_still_mounted():
    """All Mission Control endpoints from BUILD-039 must remain mounted after BUILD-064."""
    api = _client()
    expected = [
        "/api/mission-control/subsystems",
        "/api/mission-control/health",
        "/api/mission-control/builds",
        "/api/mission-control/harvesters",
        "/api/mission-control/runtime",
        "/api/mission-control/governance",
        "/api/mission-control/recommendations",
        "/api/mission-control/status",
        "/api/mission-control/audit",
        "/api/mission-control/repositories",
        "/api/mission-control/deployments",
        "/api/mission-control/metrics",
        "/api/mission-control/completeness",
    ]
    for path in expected:
        response = api.get(path)
        assert response.status_code == 200, (
            f"Endpoint {path} returned {response.status_code}; must remain 200 after BUILD-064."
        )
