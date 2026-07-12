"""Tests for BUILD-064: Production Operations Activation.

Covers:
- recommendations and governance actions now marked as implemented
- GET /api/mission-control/owner/recommendations (auth-required)
- GET /api/mission-control/owner/governance (auth-required)
- POST /api/mission-control/owner/intelligence/{item_id}/promote
- Persistent session revocation helpers (persist_revoked_nonce, load_revoked_nonces)
- Session logout persists nonce revocation
- Mission Control BUILD_ID updated to BUILD-064
- executive-session backend metadata shows BUILD-064
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app
from app.security import OWNER_SESSION_COOKIE, REVOKED_OWNER_NONCES, create_owner_session_token


def configure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code-064")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "session-secret-064")
    monkeypatch.setenv("CALYX_API_KEY", "api-key-064")


def _login(client: TestClient) -> str:
    """Login and return bearer token."""
    resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-064"},
    )
    assert resp.status_code == 200
    return resp.json()["token"]


# ─── allowed_actions: recommendations and governance now implemented ──────────

def test_allowed_actions_recommendations_now_implemented(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/session",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]
    assert actions["recommendations"]["allowed"] is True, "recommendations should be allowed when authenticated"
    assert actions["recommendations"]["state"] == "owner_authorized_action"


def test_allowed_actions_governance_now_implemented(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/session",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]
    assert actions["governance"]["allowed"] is True, "governance should be allowed when authenticated"
    assert actions["governance"]["state"] == "owner_authorized_action"


def test_allowed_actions_promote_brain_knowledge_now_implemented(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/session",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]
    assert actions["promoteBrainKnowledge"]["allowed"] is True, "promoteBrainKnowledge should be allowed when authenticated"
    assert actions["promoteBrainKnowledge"]["state"] == "owner_authorized_action"
    assert actions["promoteBrainKnowledge"]["requiresConfirmation"] is True


def test_unauthenticated_all_actions_still_false(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get("/api/mission-control/owner/executive-session")
    assert resp.status_code == 200
    actions = resp.json()["allowedActions"]
    for name, action in actions.items():
        assert action["allowed"] is False, f"Expected {name} to be disallowed when unauthenticated"


# ─── GET /api/mission-control/owner/recommendations ──────────────────────────

def test_owner_recommendations_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/recommendations")
    assert resp.status_code == 401


def test_owner_recommendations_returns_200_when_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.get(
        "/api/mission-control/owner/recommendations",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["build"] == "BUILD-064"
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)
    assert "allowedActions" in body
    assert "owner" in body
    assert body["review_status"] == "owner_review_enabled"


def test_owner_recommendations_includes_allowed_actions(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/recommendations",
        headers={"Authorization": f"******"},
    ).json()
    assert body["allowedActions"]["recommendations"]["allowed"] is True


# ─── GET /api/mission-control/owner/governance ───────────────────────────────

def test_owner_governance_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/governance")
    assert resp.status_code == 401


def test_owner_governance_returns_200_when_authenticated(monkeypatch):
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
    gov = body["governance"]
    assert "north_star" in gov
    assert "policies" in gov
    assert "missions" in gov
    assert body["mutation_status"] == "read_only"
    assert "allowedActions" in body
    assert "owner" in body


def test_owner_governance_policies_present(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    body = client.get(
        "/api/mission-control/owner/governance",
        headers={"Authorization": f"******"},
    ).json()
    policies = body["governance"]["policies"]
    assert len(policies) >= 1
    policy_keys = [p.get("policy_key") for p in policies]
    assert "owner_authorization_required" in policy_keys


# ─── POST /api/mission-control/owner/intelligence/{item_id}/promote ──────────

def _seed_intelligence_item(client: TestClient, token: str) -> str:
    """Create a source briefing to get an intelligence item, return its ID."""
    resp = client.post(
        "/api/mission-control/owner/source-briefings",
        headers={"Authorization": f"******"},
        json={
            "source": "BUILD-064 Test Source",
            "raw_text": "Orchid conservation grant available.\nDeadline: 2026-09-01",
        },
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    return items[0]["id"]


def test_promote_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/mission-control/owner/intelligence/INT-FAKE/promote",
        json={"confirm": True},
    )
    assert resp.status_code == 401


def test_promote_requires_confirm_true(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.post(
        "/api/mission-control/owner/intelligence/INT-FAKE/promote",
        headers={"Authorization": f"******"},
        json={"confirm": False},
    )
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"].lower()


def test_promote_not_found_returns_404(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)

    resp = client.post(
        "/api/mission-control/owner/intelligence/INT-DOESNOTEXIST999/promote",
        headers={"Authorization": f"******"},
        json={"confirm": True},
    )
    assert resp.status_code == 404


def test_promote_success_updates_verification_state(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)
    item_id = _seed_intelligence_item(client, token)

    resp = client.post(
        f"/api/mission-control/owner/intelligence/{item_id}/promote",
        headers={"Authorization": f"******"},
        json={"confirm": True, "notes": "Verified manually by owner"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "promoted"
    assert body["build"] == "BUILD-064"
    item = body["item"]
    assert item["verification_state"] == "promoted"
    assert item["promoted_by"] is not None
    assert item["promoted_at"] is not None
    assert "Verified manually by owner" in item.get("notes", "")


def test_promote_returns_allowed_actions(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)
    item_id = _seed_intelligence_item(client, token)

    body = client.post(
        f"/api/mission-control/owner/intelligence/{item_id}/promote",
        headers={"Authorization": f"******"},
        json={"confirm": True},
    ).json()
    assert "allowedActions" in body
    assert body["allowedActions"]["promoteBrainKnowledge"]["allowed"] is True


def test_promote_already_promoted_returns_409(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login(client)
    item_id = _seed_intelligence_item(client, token)

    # First promotion succeeds
    resp1 = client.post(
        f"/api/mission-control/owner/intelligence/{item_id}/promote",
        headers={"Authorization": f"******"},
        json={"confirm": True},
    )
    assert resp1.status_code == 200

    # Second promotion on an already-promoted item should fail
    resp2 = client.post(
        f"/api/mission-control/owner/intelligence/{item_id}/promote",
        headers={"Authorization": f"******"},
        json={"confirm": True},
    )
    assert resp2.status_code == 409


# ─── Persistent session revocation helpers ────────────────────────────────────

def test_persist_revoked_nonce_adds_to_memory():
    from app.routers.owner_operations import persist_revoked_nonce
    nonce = "test-nonce-064-abc"
    REVOKED_OWNER_NONCES.discard(nonce)
    persist_revoked_nonce(nonce)
    assert nonce in REVOKED_OWNER_NONCES
    REVOKED_OWNER_NONCES.discard(nonce)


def test_load_revoked_nonces_returns_zero_without_db(monkeypatch):
    from app.routers.owner_operations import load_revoked_nonces
    monkeypatch.delenv("DATABASE_URL", raising=False)
    count = load_revoked_nonces()
    assert count == 0


def test_delete_session_revokes_nonce_persistently(monkeypatch):
    """Logout should persist the nonce revocation so it survives in-memory across the request."""
    configure(monkeypatch)
    client = TestClient(app)

    # Login to get a cookie
    login_resp = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-064"},
    )
    assert login_resp.status_code == 200

    # Verify session is valid before logout
    inspect_before = client.get("/api/mission-control/owner/session")
    assert inspect_before.json()["authenticated"] is True

    # Logout
    logout_resp = client.delete("/api/mission-control/owner/session")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "signed_out"

    # Session should now be rejected
    inspect_after = client.get("/api/mission-control/owner/session")
    assert inspect_after.json()["authenticated"] is False


# ─── Mission Control BUILD_ID updated ────────────────────────────────────────

def test_mission_control_build_id_is_064():
    from app.routers.mission_control import BUILD_ID
    assert BUILD_ID == "BUILD-064"


def test_mission_control_status_reflects_064():
    from app.routers.mission_control import mission_control_status
    status = mission_control_status()
    assert status["build"] == "BUILD-064"


# ─── executive-session backend metadata ──────────────────────────────────────

def test_executive_session_backend_build_is_064(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get("/api/mission-control/owner/executive-session")
    assert resp.status_code == 200
    backend = resp.json()["backend"]
    assert backend["version"] == "BUILD-064"
    assert backend["build"] == "BUILD-064"


# ─── Kernel registry includes BUILD-064 ──────────────────────────────────────

def test_kernel_registry_includes_build_064():
    from runtime.kernel_registry import KernelRegistryService
    registry = KernelRegistryService()
    build_ids = [b.id for b in registry.builds()]
    assert "build-064" in build_ids


def test_kernel_registry_build_064_capabilities():
    from runtime.kernel_registry import KernelRegistryService
    registry = KernelRegistryService()
    build = next(b for b in registry.builds() if b.id == "build-064")
    assert "recommendations-review" in build.capabilities
    assert "governance-review" in build.capabilities
    assert "promote-brain-knowledge" in build.capabilities
    assert "persistent-session-revocation" in build.capabilities
