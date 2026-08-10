from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

AUTHORIZED_ORIGIN = "https://orchid-continuum-frontend-vof6.onrender.com"
UNTRUSTED_ORIGIN = "https://evil.example.com"


def _preflight(
    client: TestClient,
    path: str,
    method: str,
    *,
    origin: str = AUTHORIZED_ORIGIN,
    request_headers: str = "Authorization,Content-Type,Accept",
):
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": request_headers,
        },
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/platform/capabilities", "GET"),
        ("/api/platform/homepage", "GET"),
        ("/brain/orchestrator/status", "GET"),
        ("/api/calyx/speak/conversations", "POST"),
        ("/api/calyx/speak/conversations/demo/turns", "POST"),
        ("/api/mission-control/owner/session-token", "POST"),
    ],
)
def test_authorized_origin_preflight_is_cors_enabled(path: str, method: str):
    client = TestClient(app)
    response = _preflight(client, path, method)

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == AUTHORIZED_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"
    allowed_methods = {item.strip() for item in response.headers["access-control-allow-methods"].split(",")}
    assert method in allowed_methods
    assert "OPTIONS" in allowed_methods


@pytest.mark.parametrize(
    "path",
    [
        "/api/calyx/speak/conversations",
        "/api/calyx/speak/conversations/demo/turns",
        "/api/mission-control/owner/session-token",
    ],
)
def test_post_preflight_allows_auth_and_content_headers(path: str):
    client = TestClient(app)
    response = _preflight(client, path, "POST")

    assert response.status_code == 200
    allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert "accept" in allowed_headers


def test_untrusted_origin_not_granted_credentialed_cors_access():
    client = TestClient(app)
    response = _preflight(
        client,
        "/api/calyx/speak/conversations",
        "POST",
        origin=UNTRUSTED_ORIGIN,
    )

    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") is None
    assert response.headers.get("access-control-allow-credentials") is None


def test_protected_endpoint_stays_protected_after_preflight():
    client = TestClient(app)
    preflight = _preflight(client, "/brain/orchestrator/status", "GET")
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == AUTHORIZED_ORIGIN

    protected = client.get("/brain/orchestrator/status", headers={"Origin": AUTHORIZED_ORIGIN})
    assert protected.status_code == 401
    assert protected.headers.get("access-control-allow-origin") == AUTHORIZED_ORIGIN
    assert protected.headers.get("access-control-allow-credentials") == "true"
