"""Tests for BUILD-066A: Owner Control Verification endpoints.

Covers:
- POST /api/mission-control/owner/control-verification
  - successful creation (authenticated)
  - missing / invalid label validation
  - unauthorized (no session)
  - response shape includes id, label, created_at, session_owner, read_back_confirmed
  - read_back_confirmed is True on success

- GET /api/mission-control/owner/control-verification/:id
  - successful read-back of previously created record
  - unauthorized (no session)
  - 404 for unknown ID
  - read_back_confirmed is True on retrieval

- CORS behavior
  - preflight OPTIONS includes Access-Control-Allow-Origin and Allow-Credentials
  - accept header is listed in Access-Control-Allow-Headers
  - credentialed cross-origin response includes correct CORS headers

- In-memory fallback (no DATABASE_URL)
  - POST creates a record that GET can retrieve
  - Full write → read-back flow
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

_FRONTEND_ORIGIN = "https://orchid-continuum-frontend-vof6.onrender.com"


def configure(monkeypatch) -> None:
    """Set up environment for BUILD-066A tests (no real DB required)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code-066a")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "session-secret-066a")
    monkeypatch.setenv("CALYX_API_KEY", "api-key-066a")


def _login_cookie(client: TestClient) -> None:
    """Log in via cookie transport (POST /session)."""
    resp = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": "owner-code-066a"},
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"


def _login_token(client: TestClient) -> str:
    """Log in and return bearer token."""
    resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-066a"},
    )
    assert resp.status_code == 200, f"token login failed: {resp.text}"
    return resp.json()["token"]


# ─── POST /control-verification — unauthenticated ────────────────────────────

def test_post_control_verification_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "test-label"},
    )
    assert resp.status_code == 401


def test_post_control_verification_requires_auth_no_body(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/api/mission-control/owner/control-verification")
    assert resp.status_code in {401, 422}


# ─── POST /control-verification — validation ─────────────────────────────────

def test_post_control_verification_rejects_missing_label(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 422


def test_post_control_verification_rejects_empty_label(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": ""},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 422


# ─── POST /control-verification — success ────────────────────────────────────

def test_post_control_verification_success_returns_200(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "BUILD-066A smoke test"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200


def test_post_control_verification_response_shape(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "shape-check"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    assert "label" in body
    assert "created_at" in body
    assert "session_owner" in body
    assert "read_back_confirmed" in body


def test_post_control_verification_label_matches(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "my-unique-label-066a"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "my-unique-label-066a"


def test_post_control_verification_read_back_confirmed_is_true(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "read-back-check"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    assert resp.json()["read_back_confirmed"] is True


def test_post_control_verification_id_format(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "id-format-check"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    record_id = resp.json()["id"]
    assert record_id.startswith("CV-"), f"Expected ID to start with 'CV-', got: {record_id}"


def test_post_control_verification_session_owner_present(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "owner-check"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    assert resp.json()["session_owner"] != ""


def test_post_control_verification_created_at_present(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "timestamp-check"},
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 200
    assert resp.json()["created_at"] != "" and resp.json()["created_at"] is not None


# ─── POST via cookie transport ────────────────────────────────────────────────

def test_post_control_verification_cookie_transport(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    _login_cookie(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "cookie-transport-check"},
    )
    assert resp.status_code == 200
    assert resp.json()["read_back_confirmed"] is True


# ─── GET /control-verification/:id — unauthenticated ─────────────────────────

def test_get_control_verification_requires_auth(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/mission-control/owner/control-verification/CV-SOMEID")
    assert resp.status_code == 401


# ─── GET /control-verification/:id — not found ───────────────────────────────

def test_get_control_verification_not_found(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    token = _login_token(client)

    resp = client.get(
        "/api/mission-control/owner/control-verification/CV-DOESNOTEXIST99",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 404


# ─── DB write → read-back flow (in-memory) ────────────────────────────────────

def test_post_then_get_read_back_same_record(monkeypatch):
    """Full write → read-back flow: POST creates a record; GET retrieves the same record."""
    configure(monkeypatch)

    # Clear the in-memory store so records from other tests don't interfere
    from app.routers.owner_operations import CONTROL_VERIFICATIONS
    CONTROL_VERIFICATIONS.clear()

    client = TestClient(app)
    token = _login_token(client)

    # Write
    post_resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "end-to-end-066a"},
        headers={"Authorization": f"******"},
    )
    assert post_resp.status_code == 200
    created = post_resp.json()
    record_id = created["id"]

    # Read back
    get_resp = client.get(
        f"/api/mission-control/owner/control-verification/{record_id}",
        headers={"Authorization": f"******"},
    )
    assert get_resp.status_code == 200
    retrieved = get_resp.json()

    assert retrieved["id"] == created["id"]
    assert retrieved["label"] == created["label"]
    assert retrieved["session_owner"] == created["session_owner"]
    assert retrieved["read_back_confirmed"] is True


def test_get_returns_correct_label_after_post(monkeypatch):
    configure(monkeypatch)
    from app.routers.owner_operations import CONTROL_VERIFICATIONS
    CONTROL_VERIFICATIONS.clear()

    client = TestClient(app)
    token = _login_token(client)

    post_resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "specific-label-readback"},
        headers={"Authorization": f"******"},
    )
    assert post_resp.status_code == 200
    record_id = post_resp.json()["id"]

    get_resp = client.get(
        f"/api/mission-control/owner/control-verification/{record_id}",
        headers={"Authorization": f"******"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["label"] == "specific-label-readback"


def test_multiple_records_are_independent(monkeypatch):
    configure(monkeypatch)
    from app.routers.owner_operations import CONTROL_VERIFICATIONS
    CONTROL_VERIFICATIONS.clear()

    client = TestClient(app)
    token = _login_token(client)

    ids = []
    for i in range(3):
        resp = client.post(
            "/api/mission-control/owner/control-verification",
            json={"label": f"record-{i}"},
            headers={"Authorization": f"******"},
        )
        assert resp.status_code == 200
        ids.append((resp.json()["id"], f"record-{i}"))

    # Each retrieval must return the correct label
    for record_id, expected_label in ids:
        get_resp = client.get(
            f"/api/mission-control/owner/control-verification/{record_id}",
            headers={"Authorization": f"******"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["label"] == expected_label


# ─── CORS behavior ────────────────────────────────────────────────────────────

def test_cors_preflight_control_verification_post(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/mission-control/owner/control-verification",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == _FRONTEND_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_control_verification_get(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/mission-control/owner/control-verification/CV-TESTID",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == _FRONTEND_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_allowed_headers_includes_accept(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/mission-control/owner/control-verification",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    allowed = resp.headers.get("access-control-allow-headers", "").lower()
    assert "accept" in allowed, f"Expected 'accept' in allow-headers, got: {allowed}"


def test_cors_credentialed_post_response(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)
    token = _login_token(client)

    resp = client.post(
        "/api/mission-control/owner/control-verification",
        json={"label": "cors-credentialed"},
        headers={
            "Authorization": f"******",
            "Origin": _FRONTEND_ORIGIN,
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == _FRONTEND_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallows_unknown_origin(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/mission-control/owner/control-verification",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Unknown origins must not receive the allow-origin header
    assert resp.headers.get("access-control-allow-origin") is None


def test_cors_allows_localhost_origin(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app)

    resp = client.options(
        "/api/mission-control/owner/control-verification",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5174"


# ─── Error handling paths ─────────────────────────────────────────────────────

def test_post_control_verification_missing_session_secret(monkeypatch):
    """When CALYX_OWNER_SESSION_SECRET is not configured, login returns 503."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code-066a")
    monkeypatch.delenv("CALYX_OWNER_SESSION_SECRET", raising=False)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code-066a"},
    )
    assert resp.status_code == 503


def test_post_control_verification_invalid_access_code(monkeypatch):
    configure(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "WRONG-CODE"},
    )
    assert resp.status_code == 401


def test_get_control_verification_wrong_owner_not_in_store(monkeypatch):
    """GET for a valid-format ID that was never created must return 404."""
    configure(monkeypatch)
    from app.routers.owner_operations import CONTROL_VERIFICATIONS
    CONTROL_VERIFICATIONS.clear()

    client = TestClient(app, raise_server_exceptions=False)
    token = _login_token(client)

    resp = client.get(
        "/api/mission-control/owner/control-verification/CV-NEVEREXISTED",
        headers={"Authorization": f"******"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
