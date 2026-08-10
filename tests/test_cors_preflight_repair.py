"""Regression tests for the production CORS preflight repair.

Root cause: OPTIONS preflight requests from the deployed Orchid Continuum
frontend were returning 405 Method Not Allowed because FastAPI had no
OPTIONS route registered for several API paths.  The app-level middleware
added CORS headers to the 405 response, but browsers require a 2xx status
to honour a preflight, so every browser request failed.

Fix: the middleware now short-circuits OPTIONS requests from allowed origins,
returning 200 immediately with full CORS headers before the router runs.

Test coverage (A–F per the repair spec):
  A. Authorised OPTIONS receives 200
  B. Access-Control-Allow-Origin echoes the requesting allowed origin
  C. Credentialed CORS (allow-credentials: true) is set
  D. POST preflight permits Content-Type and Authorization
  E. Untrusted origins receive no credentialed CORS headers
  F. Protected endpoints remain protected after preflight succeeds
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

ORIGIN = "https://orchid-continuum-frontend-vof6.onrender.com"
BAD_ORIGIN = "https://attacker.example.com"

# Paths that were previously failing with 405 on OPTIONS
PREFLIGHT_PATHS = [
    "/api/platform/capabilities",
    "/api/platform/homepage",
    "/brain/orchestrator/status",
    "/api/calyx/speak/conversations",
    "/api/calyx/speak/conversations/some-id/turns",
    "/api/mission-control/owner/session-token",
]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "owner-session-secret")
    monkeypatch.setenv("CALYX_API_KEY", "server-api-key")
    return TestClient(app, raise_server_exceptions=False)


# ── A & B: authorised preflight returns 200 and echoes origin ────────────────

@pytest.mark.parametrize("path", PREFLIGHT_PATHS)
def test_authorised_options_returns_200(client, path):
    """A. Authorised frontend OPTIONS request receives a successful response."""
    resp = client.options(path, headers={"Origin": ORIGIN})
    assert resp.status_code == 200, f"Expected 200 for OPTIONS {path}, got {resp.status_code}"


@pytest.mark.parametrize("path", PREFLIGHT_PATHS)
def test_allow_origin_echoes_authorised_origin(client, path):
    """B. Access-Control-Allow-Origin matches the requesting authorised origin."""
    resp = client.options(path, headers={"Origin": ORIGIN})
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


# ── C: credentialed CORS ──────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PREFLIGHT_PATHS)
def test_credentials_flag_is_set(client, path):
    """C. Credentialed CORS is enabled (allow-credentials: true)."""
    resp = client.options(path, headers={"Origin": ORIGIN})
    assert resp.headers.get("access-control-allow-credentials") == "true"


# ── D: POST preflight allows required headers ─────────────────────────────────

POST_PATHS = [
    "/api/calyx/speak/conversations",
    "/api/calyx/speak/conversations/some-id/turns",
    "/api/mission-control/owner/session-token",
]


@pytest.mark.parametrize("path", POST_PATHS)
def test_post_preflight_allows_content_type_and_authorization(client, path):
    """D. POST preflight permits Content-Type and Authorization headers."""
    resp = client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    )
    assert resp.status_code == 200
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "content-type" in allow_headers
    assert "authorization" in allow_headers


# ── E: untrusted origin receives no credentialed CORS ────────────────────────

@pytest.mark.parametrize("path", PREFLIGHT_PATHS)
def test_untrusted_origin_receives_no_cors(client, path):
    """E. Untrusted origins are not granted credentialed CORS access."""
    resp = client.options(path, headers={"Origin": BAD_ORIGIN})
    # Must not set allow-origin to the bad origin
    assert resp.headers.get("access-control-allow-origin") != BAD_ORIGIN
    # Must not grant credentials to an untrusted origin
    assert resp.headers.get("access-control-allow-credentials") != "true"


# ── F: protected endpoints stay protected after preflight ────────────────────

def test_protected_endpoint_requires_auth_after_preflight(client):
    """F. Actual protected endpoints remain protected after preflight succeeds."""
    # OPTIONS preflight succeeds...
    pre = client.options(
        "/api/mission-control/owner/session-token",
        headers={"Origin": ORIGIN},
    )
    assert pre.status_code == 200

    # ...but the actual POST without credentials is still rejected.
    actual = client.post(
        "/api/mission-control/owner/session-token",
        json={},
        headers={"Origin": ORIGIN},
    )
    # Expect 401 or 422 (validation), never 200 without valid auth
    assert actual.status_code in {401, 422}
    # CORS headers are still present on the error response so the browser can read it
    assert actual.headers.get("access-control-allow-origin") == ORIGIN


def test_brain_orchestrator_status_options_succeeds(client):
    """Specific regression: /brain/orchestrator/status OPTIONS was returning 405."""
    resp = client.options(
        "/brain/orchestrator/status",
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


def test_platform_capabilities_options_succeeds(client):
    """Specific regression: /api/platform/capabilities OPTIONS was returning 405."""
    resp = client.options(
        "/api/platform/capabilities",
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


def test_platform_homepage_options_succeeds(client):
    """Specific regression: /api/platform/homepage OPTIONS was returning 405."""
    resp = client.options(
        "/api/platform/homepage",
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


def test_calyx_speak_conversations_options_succeeds(client):
    """Specific regression: /api/calyx/speak/conversations OPTIONS was returning 405."""
    resp = client.options(
        "/api/calyx/speak/conversations",
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


def test_vary_origin_is_set(client):
    """Vary: Origin must be present so caches don't serve one origin's response to another."""
    resp = client.options(
        "/api/platform/capabilities",
        headers={"Origin": ORIGIN},
    )
    assert "origin" in resp.headers.get("vary", "").lower()


def test_allowed_methods_include_put_patch_delete(client):
    """Allow-Methods must include PUT, PATCH, DELETE as well as GET/POST/OPTIONS."""
    resp = client.options(
        "/api/platform/capabilities",
        headers={"Origin": ORIGIN},
    )
    allow_methods = resp.headers.get("access-control-allow-methods", "").upper()
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        assert method in allow_methods, f"{method} not in allow-methods"
