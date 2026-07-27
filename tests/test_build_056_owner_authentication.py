
from fastapi.testclient import TestClient

from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token


def configure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "owner-session-secret")
    monkeypatch.setenv("CALYX_API_KEY", "server-api-key")
    monkeypatch.setenv("CORS_ALLOW_ORIGIN", "https://example.test")


def test_cookie_session_login_inspect_logout_and_secret_safety(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    missing = client.post("/api/mission-control/owner/session", json={})
    assert missing.status_code == 422
    rejected = client.post("/api/mission-control/owner/session", json={"access_code": "wrong"})
    assert rejected.status_code == 401

    login = client.post("/api/mission-control/owner/session", json={"access_code": "owner-code"})
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert login.json()["token"] == "cookie"
    assert OWNER_SESSION_COOKIE in login.cookies
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "owner-code" not in login.text and "owner-session-secret" not in login.text

    inspected = client.get("/api/mission-control/owner/session")
    assert inspected.json()["authenticated"] is True
    assert inspected.json()["allowedActions"]["runtimeStart"]["allowed"] is True

    assert client.post("/api/runner/autonomous-cycle").status_code == 200
    assert client.delete("/api/mission-control/owner/session").status_code == 200
    assert client.get("/api/mission-control/owner/session").json()["reason"] == "missing_session"
    assert client.post("/api/runner/autonomous-cycle").status_code == 401


def test_expired_tampered_api_key_cors_and_configuration(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    expired = create_owner_session_token("owner", ttl_seconds=-1)["token"]
    client.cookies.set(OWNER_SESSION_COOKIE, expired)
    assert client.get("/api/mission-control/owner/session").json()["reason"] == "expired"

    client.cookies.set(OWNER_SESSION_COOKIE, f"{expired}tampered")
    assert client.get("/api/mission-control/owner/session").json()["reason"] == "invalid_session"
    client.cookies.clear()
    assert client.post("/api/runner/autonomous-cycle", headers={"X-API-Key": "server-api-key"}).status_code == 200

    preflight = client.options(
        "/api/mission-control/owner/session",
        headers={"Origin": "https://example.test", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.headers["access-control-allow-origin"] == "https://example.test"
    assert preflight.headers["access-control-allow-credentials"] == "true"

    config = client.get("/api/runtime/configuration")
    assert config.json()["owner_auth_ready"] is True
    assert config.json()["allowed_origin_configured"] is True
    for secret in ("owner-code", "owner-session-secret", "server-api-key"):
        assert secret not in config.text
