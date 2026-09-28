"""Legacy product feedback: public submission, owner-only list, bounded input.

``GET /api/feedback`` returns visitors' free text and organization ids, so it is
owner-only (owner session or API key); a verified member gets 403
OWNER_ACCESS_REQUIRED like other owner-only product routes. ``POST /api/feedback``
stays anonymous but rejects over-long strings with 422. Supabase is always mocked.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import member_auth
from app.database import get_db
from app.main import app
from app.models import Feedback
from app.routers.feedback import (
    FEEDBACK_LABEL_MAX_CHARS,
    FEEDBACK_LIST_DEFAULT_LIMIT,
    FEEDBACK_LIST_MAX_LIMIT,
    FEEDBACK_TEXT_MAX_CHARS,
)
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

SUPABASE_GET = "app.university.learner_auth.requests.get"
MEMBER_UUID = "22222222-2222-2222-2222-222222222222"
API_KEY = "test-api-key"
URL = "/api/feedback"
OWNER_ACCESS_REQUIRED_BODY = {
    "detail": {"code": "OWNER_ACCESS_REQUIRED", "message": "This view is limited to owner access"}
}
FEEDBACK_OUT_KEYS = {"id", "organization_id", "module", "step", "worked", "confusion", "suggestions", "created_at"}


def _jwt(sub: str = MEMBER_UUID, marker: str = "a") -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc({'sub': sub, 'exp': int(time.time() + 3600), 'm': marker})}.sig"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("OC_MEMBER_READS_ENABLED", "OCU_SUPABASE_URL", "OCU_SUPABASE_ANON_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-owner-secret")
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    member_auth.clear_member_token_cache()
    yield
    member_auth.clear_member_token_cache()


@pytest.fixture
def session_local():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Feedback.__table__.create(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(session_local) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"id": MEMBER_UUID, "email": "member@example.org"}
    mock = Mock(return_value=response)
    monkeypatch.setattr(SUPABASE_GET, mock)
    return mock


@pytest.fixture
def owner_token() -> str:
    return str(create_owner_session_token("owner")["token"])


def _naive_utc(*args: int) -> datetime:
    """The ``feedback.created_at`` column stores naive UTC (``datetime.utcnow``)."""
    return datetime(*args, tzinfo=UTC).replace(tzinfo=None)


def _seed(session_local, count: int, module: str = "identify") -> list[str]:
    """Insert ``count`` rows with strictly decreasing created_at; return ids newest first."""
    start = _naive_utc(2026, 9, 1, 12, 0, 0)
    ids = []
    with session_local() as db:
        for index in range(count):
            row = Feedback(
                id=f"fb-{index:05d}",
                module=module,
                step="upload",
                worked=index % 2 == 0,
                confusion=f"confusion {index}",
                suggestions=None,
                organization_id=None,
                created_at=start - timedelta(minutes=index),
            )
            db.add(row)
            ids.append(row.id)
        db.commit()
    return ids


# --- list is owner-only -----------------------------------------------------------------


def test_anonymous_list_is_401_and_reveals_no_rows(client, session_local):
    _seed(session_local, 3)
    response = client.get(URL)
    assert response.status_code == 401
    assert "confusion" not in response.text
    # Auth runs before query validation: an out-of-range limit is still 401, not 422.
    assert client.get(f"{URL}?limit=999999&offset=-1").status_code == 401
    assert client.get(f"{URL}?module=identify").status_code == 401


def test_invalid_credentials_are_401(client, session_local, supabase, owner_token):
    _seed(session_local, 1)
    assert client.get(URL, headers={"X-API-Key": "wrong-key"}).status_code == 401
    tampered = owner_token[:-1] + ("1" if owner_token.endswith("0") else "0")
    assert client.get(URL, headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    supabase.return_value = Mock(status_code=401, ok=False)
    assert client.get(URL, headers={"Authorization": f"Bearer {_jwt(marker='invalid')}"}).status_code == 401


def test_verified_member_gets_owner_access_required(client, session_local, supabase):
    _seed(session_local, 2)
    response = client.get(URL, headers={"Authorization": f"Bearer {_jwt()}"})
    assert response.status_code == 403
    assert response.json() == OWNER_ACCESS_REQUIRED_BODY
    assert supabase.called
    # Same body regardless of query parameters (no validation or data disclosure).
    bad = client.get(f"{URL}?limit=0", headers={"Authorization": f"Bearer {_jwt()}"})
    assert bad.status_code == 403 and bad.json() == OWNER_ACCESS_REQUIRED_BODY


@pytest.mark.parametrize("credential", ["api_key", "owner_bearer", "owner_cookie"])
def test_owner_and_api_key_read_the_same_body_shape(client, session_local, owner_token, credential):
    ids = _seed(session_local, 3)
    headers: dict[str, str] = {}
    if credential == "api_key":
        headers = {"X-API-Key": API_KEY}
    elif credential == "owner_bearer":
        headers = {"Authorization": f"Bearer {owner_token}"}
    else:
        client.cookies.set(OWNER_SESSION_COOKIE, owner_token)
    response = client.get(URL, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert [row["id"] for row in body] == ids
    assert all(set(row) == FEEDBACK_OUT_KEYS for row in body)
    assert body[0]["confusion"] == "confusion 0"


def test_module_filter_still_works_for_owner(client, session_local):
    _seed(session_local, 2, module="identify")
    with session_local() as db:
        db.add(Feedback(id="other-1", module="judging", created_at=_naive_utc(2026, 9, 2)))
        db.commit()
    body = client.get(f"{URL}?module=judging", headers={"X-API-Key": API_KEY}).json()
    assert [row["id"] for row in body] == ["other-1"]


# --- pagination -------------------------------------------------------------------------


def test_default_limit_bounds_the_unpaginated_list(client, session_local):
    ids = _seed(session_local, FEEDBACK_LIST_DEFAULT_LIMIT + 5)
    body = client.get(URL, headers={"X-API-Key": API_KEY}).json()
    assert FEEDBACK_LIST_DEFAULT_LIMIT == 200
    assert [row["id"] for row in body] == ids[:FEEDBACK_LIST_DEFAULT_LIMIT]


def test_limit_and_offset_page_through_newest_first(client, session_local):
    ids = _seed(session_local, 7)
    keyed = {"X-API-Key": API_KEY}
    pages = [client.get(f"{URL}?limit=3&offset={offset}", headers=keyed).json() for offset in (0, 3, 6, 9)]
    assert [[row["id"] for row in page] for page in pages] == [ids[0:3], ids[3:6], ids[6:7], []]


def test_max_limit_is_accepted_and_bounds_are_422_for_owner(client, session_local):
    _seed(session_local, 2)
    keyed = {"X-API-Key": API_KEY}
    assert FEEDBACK_LIST_MAX_LIMIT == 1000
    assert client.get(f"{URL}?limit={FEEDBACK_LIST_MAX_LIMIT}", headers=keyed).status_code == 200
    for query in (f"limit={FEEDBACK_LIST_MAX_LIMIT + 1}", "limit=0", "limit=-1", "offset=-1", "limit=abc"):
        assert client.get(f"{URL}?{query}", headers=keyed).status_code == 422, query


# --- submission stays public, but bounded ----------------------------------------------


def _full_payload(**overrides) -> dict:
    payload = {
        "module": "identify",
        "step": "upload",
        "worked": False,
        "confusion": "Could not find the upload button.",
        "suggestions": "Make it bigger.",
        "organization_id": None,
    }
    payload.update(overrides)
    return payload


def test_anonymous_submission_is_still_accepted(client, session_local):
    payload = _full_payload()
    response = client.post(URL, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == FEEDBACK_OUT_KEYS
    assert {key: body[key] for key in payload} == payload
    minimal = client.post(URL, json={"module": "identify"})
    assert minimal.status_code == 200
    assert client.get(URL, headers={"X-API-Key": API_KEY}).json()[0]["id"] in {body["id"], minimal.json()["id"]}


def test_inputs_at_the_limits_are_accepted(client, session_local):
    payload = _full_payload(
        module="m" * FEEDBACK_LABEL_MAX_CHARS,
        step="s" * FEEDBACK_LABEL_MAX_CHARS,
        confusion="c" * FEEDBACK_TEXT_MAX_CHARS,
        suggestions="é" * FEEDBACK_TEXT_MAX_CHARS,
    )
    response = client.post(URL, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == "é" * FEEDBACK_TEXT_MAX_CHARS


@pytest.mark.parametrize(
    ("field", "size"),
    [
        ("module", FEEDBACK_LABEL_MAX_CHARS + 1),
        ("step", FEEDBACK_LABEL_MAX_CHARS + 1),
        ("organization_id", FEEDBACK_LABEL_MAX_CHARS + 1),
        ("confusion", FEEDBACK_TEXT_MAX_CHARS + 1),
        ("suggestions", FEEDBACK_TEXT_MAX_CHARS + 1),
    ],
)
def test_over_long_submission_is_422_and_not_stored(client, session_local, field, size):
    response = client.post(URL, json=_full_payload(**{field: "x" * size}))
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"][-1] == field and error["type"] == "string_too_long" for error in errors)
    with session_local() as db:
        assert db.query(Feedback).count() == 0


def test_limits_are_the_documented_values():
    assert FEEDBACK_LABEL_MAX_CHARS == 200
    assert FEEDBACK_TEXT_MAX_CHARS == 4000
