"""Tests for BUILD-063: Owner Authentication Completion + Live Backend Activation.

Covers:
- GET /api/mission-control/owner/executive-session (auth-aware full state payload)
- POST /api/mission-control/owner/session/refresh (session renewal without re-login)
- CORS OPTIONS coverage for /api/runner/* and /api/harvesters/* paths
- Session restore flow: login → inspect → refresh → logout
- Permission model surfaced via executive-session
- Authenticated vs unauthenticated response structure
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token


def configure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code-063")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "session-secret-063")
    monkeypatch.setenv("CALYX_API_KEY", "api-key-063")
    monkeypatch.setenv("CORS_ALLOW_ORIGIN", "https://example.test")


# ─── Executive Session — unauthenticated ─────────────────────────────────────

def test_executive_session_unauthenticated_returns_200(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get("/api/mission-control/owner/executive-session")

    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is False
    assert body["status"] == "unauthenticated"
    assert body["owner"] is None
    assert body["reason"] == "missing_session"


def test_executive_session_unauthenticated_has_backend_metadata(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    body = client.get("/api/mission-control/owner/executive-session").json()

    assert "backend" in body
    backend = body["backend"]
    assert "version" in backend
    assert "build" in backend
    assert "repository_revision" in backend
    assert isinstance(backend["runtime_available"], bool)
    assert isinstance(backend["runtime_enabled"], bool)


def test_executive_session_unauthenticated_allowed_actions_are_false(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    body = client.get("/api/mission-control/owner/executive-session").json()

    actions = body["allowedActions"]
    for action_name, action in actions.items():
        assert action["allowed"] is False, f"Expected {action_name} to be disallowed when unauthenticated"
    assert body["permissions"] == []


def test_executive_session_unauthenticated_session_info(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    body = client.get("/api/mission-control/owner/executive-session").json()

    assert "session_info" in body
    assert body["session_info"]["refresh_available"] is False
    assert "refresh_endpoint" in body["session_info"]
    assert body["session_info"]["ttl_remaining_seconds"] is None


# ─── Executive Session — authenticated ───────────────────────────────────────

def test_executive_session_authenticated_after_login(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    login = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )
    assert login.status_code == 200

    body = client.get("/api/mission-control/owner/executive-session").json()

    assert body["authenticated"] is True
    assert body["status"] == "authenticated"
    assert body["owner"] is not None
    assert body["reason"] is None
    assert body["auth_type"] == "owner_session"
    assert body["issued_at"] is not None
    assert body["expires_at"] is not None


def test_executive_session_authenticated_permissions_enabled(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )

    body = client.get("/api/mission-control/owner/executive-session").json()

    actions = body["allowedActions"]
    assert actions["runtimeStart"]["allowed"] is True
    assert actions["runtimeStop"]["allowed"] is True
    assert actions["runtimeRestart"]["allowed"] is True
    assert actions["queueActions"]["allowed"] is True
    assert actions["generateAudit"]["allowed"] is True
    assert actions["harvesters"]["allowed"] is True

    assert len(body["permissions"]) > 0


def test_executive_session_authenticated_session_info(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )

    body = client.get("/api/mission-control/owner/executive-session").json()

    assert body["session_info"]["refresh_available"] is True
    assert body["session_info"]["ttl_remaining_seconds"] is not None
    assert body["session_info"]["ttl_remaining_seconds"] > 0


def test_executive_session_bearer_token(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, cookies={})

    token_resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-063"},
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["token"]

    resp = client.get(
        "/api/mission-control/owner/executive-session",
        headers={"Authorization": f"******"},
        cookies={},
    )
    body = resp.json()
    assert body["authenticated"] is True


def test_executive_session_expired_session(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    expired_token = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired_token)

    body = client.get("/api/mission-control/owner/executive-session").json()

    assert body["authenticated"] is False
    assert body["reason"] == "expired"
    assert body["status"] == "unauthenticated"


def test_executive_session_does_not_leak_secrets(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )
    text = client.get("/api/mission-control/owner/executive-session").text

    for secret in ("owner-code-063", "session-secret-063", "api-key-063"):
        assert secret not in text


# ─── Session Refresh ──────────────────────────────────────────────────────────

def test_session_refresh_requires_valid_session(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post("/api/mission-control/owner/session/refresh")
    assert resp.status_code == 401


def test_session_refresh_extends_valid_session(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )

    resp = client.post("/api/mission-control/owner/session/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["status"] == "refreshed"
    assert body["token"] == "cookie"
    assert OWNER_SESSION_COOKIE in resp.cookies
    assert "HttpOnly" in resp.headers["set-cookie"]


def test_session_refresh_rejects_expired_session(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    expired_token = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired_token)

    resp = client.post("/api/mission-control/owner/session/refresh")
    assert resp.status_code == 401


def test_session_refresh_new_cookie_is_httponly(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )

    resp = client.post("/api/mission-control/owner/session/refresh")
    assert "HttpOnly" in resp.headers.get("set-cookie", "")


def test_session_refresh_via_bearer_token(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, cookies={})

    token_resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-063"},
    )
    token = token_resp.json()["token"]

    resp = client.post(
        "/api/mission-control/owner/session/refresh",
        headers={"Authorization": f"******"},
        cookies={},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "refreshed"


# ─── CORS — runner preflight ──────────────────────────────────────────────────

def test_runner_start_cors_preflight(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/runner/start",
        headers={"Origin": "https://example.test", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.test"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_runner_stop_cors_preflight(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/runner/stop",
        headers={"Origin": "https://example.test", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.test"


def test_runner_restart_cors_preflight(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/runner/restart",
        headers={"Origin": "https://example.test", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.test"


def test_runner_status_cors_preflight(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/runner/autonomous-status",
        headers={"Origin": "https://example.test", "Access-Control-Request-Method": "GET"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.test"


def test_runner_cors_unknown_origin_not_reflected(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/runner/start",
        headers={"Origin": "https://attacker.evil", "Access-Control-Request-Method": "POST"},
    )
    assert resp.headers.get("access-control-allow-origin") != "https://attacker.evil"


# ─── CORS — harvesters preflight ─────────────────────────────────────────────

def test_harvesters_cors_preflight(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/harvesters/gbif/run-once",
        headers={"Origin": "https://example.test", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.test"
    assert resp.headers.get("access-control-allow-credentials") == "true"


# ─── Runner write endpoints return CORS headers ───────────────────────────────

def test_runner_authenticated_start_includes_cors_headers(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )

    resp = client.post(
        "/api/runner/start",
        headers={"Origin": "https://example.test"},
    )
    # Authenticated call should succeed and carry CORS headers
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.test"


# ─── Full session restore flow ────────────────────────────────────────────────

def test_full_session_restore_flow(monkeypatch):
    """Simulate: login → page refresh (executive-session restore) → logout → check."""
    configure(monkeypatch)
    client = TestClient(app)

    # Step 1: Login
    login = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-063"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True

    # Step 2: Page refresh — restore via executive-session
    restore = client.get("/api/mission-control/owner/executive-session")
    assert restore.status_code == 200
    assert restore.json()["authenticated"] is True
    assert restore.json()["session_info"]["refresh_available"] is True

    # Step 3: Session refresh
    refreshed = client.post("/api/mission-control/owner/session/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "refreshed"

    # Step 4: Still authenticated after refresh
    after_refresh = client.get("/api/mission-control/owner/executive-session")
    assert after_refresh.json()["authenticated"] is True

    # Step 5: Logout
    logout = client.delete("/api/mission-control/owner/session")
    assert logout.status_code == 200
    assert logout.json()["authenticated"] is False

    # Step 6: Executive-session shows unauthenticated
    after_logout = client.get("/api/mission-control/owner/executive-session")
    assert after_logout.json()["authenticated"] is False
    assert after_logout.json()["reason"] == "missing_session"
