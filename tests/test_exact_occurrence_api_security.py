import asyncio

import pytest
from fastapi import HTTPException, Request

from api_occurrence_points import require_exact_occurrence_access
from app.security import create_owner_session_token


def _request(*, authorization: str | None = None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request({"type": "http", "headers": headers})


def test_exact_occurrence_api_accepts_configured_backend_key(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "expected")
    result = asyncio.run(require_exact_occurrence_access(_request(), "expected"))
    assert result["auth_type"] == "api_key"


def test_exact_occurrence_api_rejects_wrong_backend_key(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "expected")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_exact_occurrence_access(_request(), "wrong"))
    assert exc.value.status_code == 401


def test_exact_occurrence_api_fails_closed_when_no_auth_is_configured(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    monkeypatch.delenv("CALYX_OWNER_SESSION_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_exact_occurrence_access(_request(), None))
    assert exc.value.status_code == 401


def test_exact_occurrence_api_accepts_signed_owner_session(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-owner-session-secret")
    session = create_owner_session_token("owner")
    request = _request(authorization=f"Bearer {session['token']}")
    result = asyncio.run(require_exact_occurrence_access(request, None))
    assert result["actor"] == "owner"
    assert result["auth_type"] == "owner_session"
