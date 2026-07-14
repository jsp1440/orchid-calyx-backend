"""Regression tests for the owner session system — BUILD-067.

Root cause fixed: HTTPException error responses (401, 503) from owner session
endpoints were missing CORS headers because FastAPI's default exception handler
creates a fresh response that discards headers set by route dependencies.  This
caused browsers to block the response and JavaScript to see a network error
("Load failed" in Safari, "Failed to fetch" in Chrome), which the Mission Control
frontend displayed as "Stored backend owner session rejected: Load failed".

Fix: a custom HTTPException handler in app.main adds CORS headers for allowed
origins on every error response, so browsers can read the error body and the
frontend can show the correct reason (expired, invalid_session, etc.) rather than
a generic network failure.

Tests added:
- Successful login (POST /owner/session)
- Session retrieval  (GET  /owner/session)
- Logout             (DELETE /owner/session)
- Invalid cookie     (GET  /owner/session with tampered token)
- Expired session    (GET  /owner/session with expired token)
- Incorrect owner code (POST /owner/session with wrong code)
- CORS headers present in successful responses
- CORS headers present in 401 error responses (key regression)
- CORS headers present in session-refresh failure (key regression)
- Session persists across simulated page reload
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

LOGIN_URL = "/api/mission-control/owner/session"
SESSION_URL = "/api/mission-control/owner/session"
REFRESH_URL = "/api/mission-control/owner/session/refresh"
EXECUTIVE_URL = "/api/mission-control/owner/executive-session"
PERMISSIONS_URL = "/api/mission-control/owner/permissions"

ALLOWED_ORIGIN = "https://orchid-continuum-frontend-vof6.onrender.com"
UNKNOWN_ORIGIN = "https://attacker.evil"


def configure(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "test-owner-code-067")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-session-secret-067")
    monkeypatch.setenv("CALYX_API_KEY", "test-api-key-067")


# ─── Successful login ─────────────────────────────────────────────────────────


def test_login_success_returns_200_and_cookie(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["status"] == "authenticated"
    assert body["token"] == "cookie"
    assert OWNER_SESSION_COOKIE in resp.cookies
    assert "HttpOnly" in resp.headers.get("set-cookie", "")


def test_login_success_cookie_has_max_age(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})

    assert "Max-Age" in resp.headers.get("set-cookie", "")


def test_login_success_allowed_actions_enabled(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})
    body = resp.json()

    assert body["allowedActions"]["runtimeStart"]["allowed"] is True
    assert body["allowedActions"]["runtimeStop"]["allowed"] is True


# ─── Incorrect owner code ─────────────────────────────────────────────────────


def test_login_wrong_code_returns_401(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(LOGIN_URL, json={"access_code": "wrong-code"})

    assert resp.status_code == 401


def test_login_missing_access_code_returns_422(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(LOGIN_URL, json={})

    assert resp.status_code == 422


# ─── CORS headers in error responses (key regression) ────────────────────────


def test_login_wrong_code_includes_cors_headers_for_allowed_origin(monkeypatch):
    """401 from POST /session must carry CORS headers for allowed origins.

    Without this, browsers block the response and JS sees "Load failed" instead
    of a 401 that the frontend could handle gracefully.
    """
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(
        LOGIN_URL,
        json={"access_code": "wrong-code"},
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_login_wrong_code_no_cors_headers_for_unknown_origin(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(
        LOGIN_URL,
        json={"access_code": "wrong-code"},
        headers={"Origin": UNKNOWN_ORIGIN},
    )

    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") != UNKNOWN_ORIGIN


def test_refresh_expired_session_includes_cors_headers(monkeypatch):
    """401 from POST /session/refresh must carry CORS headers for allowed origins.

    If the frontend tries to refresh a stored (but expired) session, the 401
    response must include CORS headers or the browser blocks it entirely.
    """
    configure(monkeypatch)
    client = TestClient(app)

    expired_token = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired_token)

    resp = client.post(
        REFRESH_URL,
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_permissions_unauthenticated_includes_cors_headers(monkeypatch):
    """401 from GET /permissions must carry CORS headers for allowed origins."""
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get(
        PERMISSIONS_URL,
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


# ─── CORS headers in successful responses ────────────────────────────────────


def test_login_success_includes_cors_headers(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.post(
        LOGIN_URL,
        json={"access_code": "test-owner-code-067"},
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_session_retrieval_includes_cors_headers(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})

    resp = client.get(
        SESSION_URL,
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_logout_includes_cors_headers(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})

    resp = client.delete(
        SESSION_URL,
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


# ─── Session retrieval ────────────────────────────────────────────────────────


def test_session_retrieval_authenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})

    resp = client.get(SESSION_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is True
    assert body["status"] == "authenticated"
    assert body["allowedActions"]["runtimeStart"]["allowed"] is True


def test_session_retrieval_no_cookie_returns_unauthenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.get(SESSION_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is False
    assert body["reason"] == "missing_session"


# ─── Invalid cookie ───────────────────────────────────────────────────────────


def test_invalid_cookie_returns_unauthenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.cookies.set(OWNER_SESSION_COOKIE, "completely.invalid-token")

    resp = client.get(SESSION_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is False
    assert body["reason"] == "invalid_session"


def test_tampered_cookie_returns_unauthenticated(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    # Create a valid token and append garbage to tamper the signature
    valid_token = create_owner_session_token("owner")["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, valid_token + "tampered")

    resp = client.get(SESSION_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is False
    assert body["reason"] == "invalid_session"


# ─── Expired session ──────────────────────────────────────────────────────────


def test_expired_session_returns_unauthenticated_with_reason_expired(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    expired_token = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired_token)

    resp = client.get(SESSION_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is False
    assert body["reason"] == "expired"


def test_expired_session_via_executive_endpoint(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    expired_token = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired_token)

    resp = client.get(EXECUTIVE_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is False
    assert body["reason"] == "expired"


# ─── Logout ───────────────────────────────────────────────────────────────────


def test_logout_returns_unauthenticated_status(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})

    resp = client.delete(SESSION_URL)
    body = resp.json()

    assert resp.status_code == 200
    assert body["authenticated"] is False
    assert body["status"] == "signed_out"


def test_logout_clears_cookie(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})
    assert OWNER_SESSION_COOKIE in client.cookies

    client.delete(SESSION_URL)
    assert OWNER_SESSION_COOKIE not in client.cookies


def test_session_is_invalid_after_logout(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})
    client.delete(SESSION_URL)

    resp = client.get(SESSION_URL)
    assert resp.json()["authenticated"] is False


# ─── Session persistence (page reload simulation) ────────────────────────────


def test_session_persists_across_simulated_page_reload(monkeypatch):
    """Simulate login then page reload: a new client with the same cookie should
    still be authenticated (session survives across requests).
    """
    configure(monkeypatch)

    # Step 1: Login
    login_client = TestClient(app)
    login_resp = login_client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})
    assert login_resp.status_code == 200
    cookie_value = login_client.cookies.get(OWNER_SESSION_COOKIE)
    assert cookie_value is not None

    # Step 2: Simulate page reload — fresh client with the persisted cookie
    reload_client = TestClient(app)
    reload_client.cookies.set(OWNER_SESSION_COOKIE, cookie_value)
    reload_resp = reload_client.get(SESSION_URL)

    assert reload_resp.status_code == 200
    assert reload_resp.json()["authenticated"] is True


def test_executive_session_persists_across_simulated_page_reload(monkeypatch):
    configure(monkeypatch)

    login_client = TestClient(app)
    login_resp = login_client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})
    cookie_value = login_client.cookies.get(OWNER_SESSION_COOKIE)

    reload_client = TestClient(app)
    reload_client.cookies.set(OWNER_SESSION_COOKIE, cookie_value)
    body = reload_client.get(EXECUTIVE_URL).json()

    assert body["authenticated"] is True
    assert body["session_info"]["refresh_available"] is True


# ─── No secrets leak ─────────────────────────────────────────────────────────


def test_login_response_does_not_leak_secrets(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    client.post(LOGIN_URL, json={"access_code": "test-owner-code-067"})
    text = client.get(SESSION_URL).text

    for secret in ("test-owner-code-067", "test-session-secret-067", "test-api-key-067"):
        assert secret not in text
