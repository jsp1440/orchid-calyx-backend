"""Regression tests for the owner-session CORS repair.

Root cause repaired: error responses (401 expired/invalid owner session, 422
validation errors, 401 wrong access code) were emitted by FastAPI's exception
handlers WITHOUT the Mission Control CORS headers, because those headers were
only attached by a per-route dependency on successful responses. Browsers then
blocked the response, and Mission Control surfaced "Stored backend owner
session rejected: Load failed" instead of a readable rejection.

These tests assert that every response in the owner-session flow — success and
failure alike — carries the CORS headers for an allowed origin, and that no
CORS headers leak to disallowed origins.
"""


from fastapi.testclient import TestClient

from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

ORIGIN = "https://orchid-continuum-frontend-vof6.onrender.com"
BAD_ORIGIN = "https://evil.example.com"


def configure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "owner-session-secret")
    monkeypatch.setenv("CALYX_API_KEY", "server-api-key")


def assert_cors(response):
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_successful_login_inspect_logout_have_cors(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    login = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert OWNER_SESSION_COOKIE in login.cookies
    assert_cors(login)

    inspected = client.get(
        "/api/mission-control/owner/session", headers={"Origin": ORIGIN}
    )
    assert inspected.status_code == 200
    assert inspected.json()["authenticated"] is True
    assert_cors(inspected)

    logout = client.delete(
        "/api/mission-control/owner/session", headers={"Origin": ORIGIN}
    )
    assert logout.status_code == 200
    assert_cors(logout)

    after = client.get(
        "/api/mission-control/owner/session", headers={"Origin": ORIGIN}
    )
    assert after.json()["authenticated"] is False
    assert_cors(after)


def test_incorrect_owner_code_401_has_cors(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    rejected = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "wrong"},
        headers={"Origin": ORIGIN},
    )
    assert rejected.status_code == 401
    assert_cors(rejected)


def test_validation_error_422_has_cors(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    missing = client.post(
        "/api/mission-control/owner/session",
        json={},
        headers={"Origin": ORIGIN},
    )
    assert missing.status_code == 422
    assert_cors(missing)

    token_missing = client.post(
        "/api/mission-control/owner/session-token",
        json={},
        headers={"Origin": ORIGIN},
    )
    assert token_missing.status_code == 422
    assert_cors(token_missing)


def test_invalid_cookie_rejection_is_readable(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    client.cookies.set(OWNER_SESSION_COOKIE, "garbage.invalid")

    inspected = client.get(
        "/api/mission-control/owner/session", headers={"Origin": ORIGIN}
    )
    assert inspected.status_code == 200
    assert inspected.json()["authenticated"] is False
    assert_cors(inspected)

    guarded = client.get(
        "/api/mission-control/owner/permissions", headers={"Origin": ORIGIN}
    )
    assert guarded.status_code == 401
    assert_cors(guarded)


def test_expired_session_rejection_is_readable(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    expired = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired)

    inspected = client.get(
        "/api/mission-control/owner/session", headers={"Origin": ORIGIN}
    )
    assert inspected.status_code == 200
    assert inspected.json()["reason"] == "expired"
    assert_cors(inspected)

    guarded = client.get(
        "/api/mission-control/owner/permissions", headers={"Origin": ORIGIN}
    )
    assert guarded.status_code == 401
    assert_cors(guarded)


def test_bearer_fallback_error_has_cors(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    guarded = client.get(
        "/api/mission-control/owner/permissions",
        headers={"Origin": ORIGIN, "Authorization": "Bearer garbage.token"},
    )
    assert guarded.status_code == 401
    assert_cors(guarded)


def test_unconfigured_owner_access_503_has_cors(monkeypatch):
    configure(monkeypatch)
    monkeypatch.delenv("CALYX_OWNER_ACCESS_CODE", raising=False)
    client = TestClient(app)
    resp = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "anything"},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 503
    assert_cors(resp)


def test_disallowed_origin_receives_no_cors_headers(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "wrong"},
        headers={"Origin": BAD_ORIGIN},
    )
    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") is None
    assert resp.headers.get("access-control-allow-credentials") is None
