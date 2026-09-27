"""/api/research/projects* is owner-only: a verified member gets 403, not 401.

The research-project routers used plain ``verify_owner_or_api_key``, which treats
any bearer as an owner token, so a signed-in member was told 401 "Invalid owner
session". They now carry the default-deny ``owner_or_member_read`` dependency with
no ``@member_readable`` route, exactly like the other owner-only product routers:
a verified member gets 403 OWNER_ACCESS_REQUIRED before validation or any lookup,
while owner, API-key and anonymous responses are unchanged.

Supabase is always mocked; these tests never reach the network.
"""

from __future__ import annotations

import base64
import json
import re
import time
from unittest.mock import Mock

import pytest
import requests
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import member_auth
from app.database import Base, get_db
from app.main import app
from app.reasoning_ledger.persistence import TABLES as LEDGER_TABLES
from app.research_workspace.models import (
    AuditEvent,
    Note,
    Project,
    ProjectDocument,
    ProjectEvidence,
    ProjectTaxon,
    SavedSearch,
)
from app.scientific_memory.models import (
    ScientificMemoryCapture,
    ScientificMemoryDecision,
    ScientificMemoryItem,
)
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

PREFIX = "/api/research/projects"
API_KEY = "projects-api-key"
SUPABASE_GET = "app.university.learner_auth.requests.get"
MEMBER_UUID = "33333333-3333-3333-3333-333333333333"
MISSING_PROJECT = "00000000-0000-0000-0000-000000000000"
OWNER_ACCESS_REQUIRED_BYTES = json.dumps(
    {"detail": {"code": "OWNER_ACCESS_REQUIRED", "message": "This view is limited to owner access"}},
    separators=(",", ":"),
).encode()
# Every route under the prefix, so a new one cannot arrive unreviewed.
EXPECTED_ROUTES = {
    ("GET", PREFIX),
    ("POST", PREFIX),
    ("GET", PREFIX + "/{project_id}"),
    ("PATCH", PREFIX + "/{project_id}"),
    ("POST", PREFIX + "/{project_id}/archive"),
    ("POST", PREFIX + "/{project_id}/restore"),
    ("GET", PREFIX + "/{project_id}/saved-searches"),
    ("POST", PREFIX + "/{project_id}/saved-searches"),
    ("GET", PREFIX + "/{project_id}/notes"),
    ("POST", PREFIX + "/{project_id}/notes"),
    ("GET", PREFIX + "/{project_id}/taxa"),
    ("POST", PREFIX + "/{project_id}/taxa"),
    ("DELETE", PREFIX + "/{project_id}/taxa/{taxon_id}"),
    ("GET", PREFIX + "/{project_id}/documents"),
    ("POST", PREFIX + "/{project_id}/documents"),
    ("DELETE", PREFIX + "/{project_id}/documents/{document_id}"),
    ("GET", PREFIX + "/{project_id}/evidence"),
    ("POST", PREFIX + "/{project_id}/evidence"),
    ("DELETE", PREFIX + "/{project_id}/evidence/{evidence_kind}/{evidence_id}"),
    ("GET", PREFIX + "/{project_id}/activity"),
    ("POST", PREFIX + "/{project_id}/scientific-memory/captures"),
    ("GET", PREFIX + "/{project_id}/scientific-memory"),
    ("POST", PREFIX + "/{project_id}/scientific-memory/items/{item_id}/decisions"),
    ("GET", PREFIX + "/{project_id}/epistemic-memory"),
    ("GET", PREFIX + "/{project_id}/reasoning-ledgers"),
}
TABLES = [
    Project.__table__,
    SavedSearch.__table__,
    Note.__table__,
    ProjectTaxon.__table__,
    ProjectDocument.__table__,
    ProjectEvidence.__table__,
    AuditEvent.__table__,
    ScientificMemoryCapture.__table__,
    ScientificMemoryItem.__table__,
    ScientificMemoryDecision.__table__,
    *LEDGER_TABLES,
]


def _jwt(marker: str = "a") -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"sub": MEMBER_UUID, "exp": int(time.time() + 3600), "m": marker}
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.sig"


def _supabase_ok() -> Mock:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"id": MEMBER_UUID, "email": "member@example.org"}
    return response


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("OC_MEMBER_READS_ENABLED", "OCU_SUPABASE_URL", "OCU_SUPABASE_ANON_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "projects-owner-secret")
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    member_auth.clear_member_token_cache()
    yield
    member_auth.clear_member_token_cache()


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    mock = Mock(return_value=_supabase_ok())
    monkeypatch.setattr(SUPABASE_GET, mock)
    return mock


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    # Both schemas have an audit_events table; keep the ledger's in its own schema.
    event.listen(
        engine, "connect", lambda connection, _record: connection.execute("ATTACH DATABASE ':memory:' AS reasoning_ledger")
    )
    Base.metadata.create_all(engine, tables=TABLES)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield session_local
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(db_session) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def owner() -> dict[str, str]:
    return _bearer(str(create_owner_session_token("owner")["token"]))


@pytest.fixture
def project_id(client, owner) -> str:
    created = client.post(PREFIX, json={"title": "Owner project"}, headers=owner)
    assert created.status_code == 201, created.text
    return created.json()["project_id"]


def _routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PREFIX)
        for method in route.methods
    }


def _url(path: str, project: str) -> str:
    values = {"project_id": project, "evidence_kind": "CANDIDATE"}
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), "1"), path)


def _projects(session_local) -> int:
    with session_local() as db:
        return db.scalar(select(func.count()).select_from(Project))


# --- declared surface ----------------------------------------------------------------


def test_every_research_project_route_is_owner_only_and_gated():
    assert _routes() == EXPECTED_ROUTES
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith(PREFIX):
            assert not getattr(route.endpoint, member_auth.MEMBER_READABLE_ATTR, False), route.path
            calls = [dependency.call for dependency in route.dependant.dependencies]
            assert member_auth.owner_or_member_read in calls, route.path


# --- members: 403, identical, before validation and lookup ----------------------------


def test_member_gets_identical_403_on_every_route_whether_or_not_the_project_exists(
    client, supabase, project_id, db_session
):
    member = _bearer(_jwt())
    before = _projects(db_session)
    bodies, failures = set(), []
    for method, path in sorted(EXPECTED_ROUTES):
        for project in (project_id, MISSING_PROJECT, "not-a-uuid"):
            for kwargs in ({}, {"json": {"not": "valid"}}, {"json": {"title": "Member write"}}, {"content": b'{"title": "\\ud800"}'}):
                response = client.request(method, _url(path, project), headers=member, **kwargs)
                if response.status_code != 403:
                    failures.append((method, path, project, response.status_code, response.text[:120]))
                bodies.add(response.content)
    assert not failures, failures
    assert bodies == {OWNER_ACCESS_REQUIRED_BYTES}
    assert _projects(db_session) == before


def test_member_list_create_and_read_are_refused(client, supabase, project_id):
    member = _bearer(_jwt())
    for method, url in [
        ("GET", PREFIX),
        ("POST", PREFIX),
        ("GET", f"{PREFIX}/{project_id}"),
        ("GET", f"{PREFIX}/{project_id}/notes"),
        ("GET", f"{PREFIX}/{project_id}/scientific-memory"),
        ("GET", f"{PREFIX}/{project_id}/reasoning-ledgers"),
    ]:
        response = client.request(method, url, headers=member, json={"title": "x"})
        assert (response.status_code, response.content) == (403, OWNER_ACCESS_REQUIRED_BYTES), (method, url)


def test_unverifiable_member_keeps_the_owner_path_401(client, supabase, monkeypatch):
    # Unchanged from before: a bearer that is not a verified member stays 401.
    supabase.return_value = Mock(status_code=401, ok=False)
    rejected = client.get(PREFIX, headers=_bearer(_jwt("rejected")))
    assert (rejected.status_code, rejected.json()) == (401, {"detail": "Invalid owner session"})

    supabase.return_value = _supabase_ok()
    supabase.side_effect = requests.ConnectionError("down")
    down = client.get(PREFIX, headers=_bearer(_jwt("down")))
    assert (down.status_code, down.json()) == (401, {"detail": "Invalid owner session"})

    supabase.side_effect = None
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    switched_off = client.get(PREFIX, headers=_bearer(_jwt("off")))
    assert (switched_off.status_code, switched_off.json()) == (401, {"detail": "Invalid owner session"})


# --- owner, API key and anonymous: byte-identical to the ungated router ---------------


def _credentials(owner_headers: dict[str, str]) -> dict[str, dict]:
    owner_token = owner_headers["Authorization"].split(" ", 1)[1]
    return {
        "owner-bearer": {"headers": owner_headers},
        "owner-cookie": {"cookies": {OWNER_SESSION_COOKIE: owner_token}},
        "api-key": {"headers": {"X-API-Key": API_KEY}},
        "wrong-api-key": {"headers": {"X-API-Key": "wrong"}},
        "anonymous": {},
        "bad-owner-shaped-bearer": {"headers": _bearer("abc." + "0" * 64)},
        "non-bearer-authorization": {"headers": {"Authorization": "Basic abc"}},
    }


def _deterministic_requests(project_id: str) -> list[tuple[str, str, dict]]:
    requests_ = []
    for method, path in sorted(EXPECTED_ROUTES):
        for project in (MISSING_PROJECT, project_id):
            if project == project_id and path.endswith(("/archive", "/restore")):
                continue  # bodiless writes that would succeed and change state
            url = _url(path, project)
            if method == "GET":
                requests_.append((method, url, {}))
            else:
                # Invalid bodies: validation 422 or not-found, never a write.
                requests_.append((method, url, {"json": {"not": "valid"}}))
    return requests_


def test_owner_api_key_and_anonymous_responses_are_byte_identical_to_the_ungated_router(
    client, supabase, owner, project_id, db_session
):
    before = _projects(db_session)
    credentials = _credentials(owner)
    differences, statuses = [], {}
    for label, auth in credentials.items():
        headers = auth.get("headers", {})
        client.cookies.clear()
        for name, value in auth.get("cookies", {}).items():
            client.cookies.set(name, value)
        for method, url, body in _deterministic_requests(project_id):
            gated = client.request(method, url, headers=headers, **body)
            app.dependency_overrides[member_auth.owner_or_member_read] = lambda: None
            try:
                ungated = client.request(method, url, headers=headers, **body)
            finally:
                app.dependency_overrides.pop(member_auth.owner_or_member_read, None)
            if (gated.status_code, gated.content) != (ungated.status_code, ungated.content):
                differences.append((label, method, url, gated.status_code, ungated.status_code))
            statuses.setdefault(label, set()).add(gated.status_code)
    client.cookies.clear()
    assert not differences, differences
    # The comparison covered admitted owner/API-key requests, not only refusals.
    for label in ("owner-bearer", "owner-cookie", "api-key"):
        assert {200, 404, 422} <= statuses[label], (label, statuses[label])
    for label in ("wrong-api-key", "anonymous", "bad-owner-shaped-bearer", "non-bearer-authorization"):
        assert statuses[label] == {401}, (label, statuses[label])
    assert _projects(db_session) == before
    supabase.assert_not_called()


def test_owner_and_api_key_still_create_list_and_read(client, supabase, owner):
    created = client.post(PREFIX, json={"title": "Owner project"}, headers=owner)
    assert created.status_code == 201
    project = created.json()["project_id"]
    assert client.get(f"{PREFIX}/{project}", headers=owner).json()["title"] == "Owner project"
    by_key = client.post(PREFIX, json={"title": "Key project"}, headers={"X-API-Key": API_KEY})
    assert by_key.status_code == 201
    listed = client.get(PREFIX, headers={"X-API-Key": API_KEY})
    assert listed.status_code == 200 and listed.json()["total"] == 2
    anonymous = client.get(PREFIX)
    assert (anonymous.status_code, anonymous.json()) == (401, {"detail": "Owner session or API key is required"})
    supabase.assert_not_called()
