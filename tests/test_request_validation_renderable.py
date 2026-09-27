"""Malformed request input is a 422 on every JSON endpoint, never a 500.

FastAPI's default RequestValidationError handler echoes each error's ``input``.
A lone UTF-16 surrogate (``"\\ud800"``) or a non-finite number (``NaN``) in a JSON
body cannot be rendered by JSONResponse, so the default handler itself raised
and every JSON endpoint answered 500. ``app.validation_errors`` renders the same
422 body with only the unrenderable values changed.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI, Query
from fastapi.exception_handlers import (
    request_validation_exception_handler as fastapi_default_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.research_workspace.models import (
    AuditEvent,
    Note,
    Project,
    ProjectDocument,
    ProjectEvidence,
    ProjectTaxon,
    SavedSearch,
)
from app.research_workspace.schemas import ProjectCreate
from app.scientific_memory.models import (
    ScientificMemoryCapture,
    ScientificMemoryDecision,
    ScientificMemoryItem,
)
from app.validation_errors import (
    MAX_ECHOED_INPUT_CHARS,
    renderable_validation_errors,
    request_validation_exception_handler,
)

API_KEY = "validation-api-key"
JSON = {"content-type": "application/json"}
KEYED = {**JSON, "X-API-Key": API_KEY}
LONE_SURROGATE_BODY = b'{"title": "\\ud800"}'
TEXT = {"content-type": "text/plain"}
UNDECODABLE_BODY = b"\xff\xfe"
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
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(engine, tables=TABLES)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _assert_renderable_422(response) -> list[dict]:
    assert response.status_code == 422, (response.status_code, response.text[:300])
    assert response.headers["content-type"] == "application/json"
    response.content.decode("utf-8", errors="strict")
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for error in detail:
        assert {"type", "loc", "msg"} <= set(error)
        assert "\ud800" not in json.dumps(error, ensure_ascii=False)
    return detail


def _project(client) -> str:
    created = client.post("/api/research/projects", json={"title": "Validation"}, headers=KEYED)
    assert created.status_code == 201, created.text
    return created.json()["project_id"]


# --- end to end on the real app ------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/feedback",  # public JSON endpoint
        "/api/research/projects",  # authenticated JSON endpoint
        "/api/mission-control/owner/session",  # owner login
    ],
)
@pytest.mark.parametrize(
    "body",
    [
        LONE_SURROGATE_BODY,
        b'{"access_code": "\\udfff", "title": "x"}',
        b'{"\\ud800": 1}',
        b'["\\ud800"]',
        b'{"title": NaN}',
        b'{"title": Infinity, "rating": -Infinity}',
    ],
    ids=["surrogate", "low-surrogate", "surrogate-key", "surrogate-in-array", "nan", "infinity"],
)
def test_malformed_json_body_is_422_on_representative_routes(client, path, body):
    detail = _assert_renderable_422(client.post(path, content=body, headers=KEYED))
    for error in detail:
        if error["type"] == "string_unicode":
            assert "input" not in error


def test_string_unicode_error_keeps_loc_msg_type_and_drops_the_input(client):
    detail = _assert_renderable_422(client.post("/api/research/projects", content=LONE_SURROGATE_BODY, headers=KEYED))
    assert detail == [
        {
            "type": "string_unicode",
            "loc": ["body", "title"],
            "msg": "Input should be a valid string, unable to parse raw data as a unicode string",
        }
    ]


def test_surrogate_in_nested_body_field_on_a_path_route(client):
    project_id = _project(client)
    for path, body in [
        (f"/api/research/projects/{project_id}/notes", b'{"body": "note \\ud83d"}'),
        (f"/api/research/projects/{project_id}", b'{"title": "\\ud800", "expected_version": 1}'),
        (f"/api/research/projects/{project_id}/taxa", b'{"taxon_id": "\\udc00"}'),
    ]:
        method = "PATCH" if path.endswith(project_id) else "POST"
        _assert_renderable_422(client.request(method, path, content=body, headers=KEYED))


def test_percent_encoded_surrogate_bytes_in_query_and_path_never_500(client):
    # UTF-8-encoded surrogate bytes cannot survive URL decoding as a surrogate
    # (they decode to U+FFFD), but the echoed value must still render.
    detail = _assert_renderable_422(client.get("/api/research/projects?status=%ED%A0%80", headers=KEYED))
    assert detail[0]["loc"] == ["query", "status"]
    assert _assert_renderable_422(client.get("/api/research/projects?limit=%ED%A0%80", headers=KEYED))
    missing = client.get("/api/research/projects/%ED%A0%80", headers=KEYED)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.parametrize(
    "body",
    [
        b'{"name": "s", "query": {"q": "\\ud800"}}',
        b'{"name": "s", "query": {"\\ud800": "q"}}',
        b'{"name": "s", "query": {"q": NaN}}',
        b'{"name": "s", "query": {"q": [Infinity]}}',
    ],
)
def test_free_form_saved_search_query_rejects_unrenderable_json_before_storage(client, body):
    project_id = _project(client)
    url = f"/api/research/projects/{project_id}/saved-searches"
    detail = _assert_renderable_422(client.post(url, content=body, headers=KEYED))
    assert detail[0]["loc"][:2] == ["body", "query"]
    # Nothing was stored, so the listing still renders.
    listing = client.get(url, headers=KEYED)
    assert listing.status_code == 200 and listing.json()["items"] == []
    ordinary = client.post(url, json={"name": "s", "query": {"q": "Dracula é"}}, headers=KEYED)
    assert ordinary.status_code == 201, ordinary.text


def test_free_form_scientific_memory_fields_reject_unrenderable_json(client):
    project_id = _project(client)
    item = {
        "item_type": "CLAIM",
        "authority": "RESEARCH_CONTEXT",
        "statement": "A research-context note.",
        "source": {"rights_basis": "USER_PROVIDED", "locator": {"page": 1}},
        "structured_payload": {"k": "v"},
    }
    capture = {"origin": "RESEARCH_STATION", "name": "c", "query": "q", "filters": {}, "items": [item]}
    url = f"/api/research/projects/{project_id}/scientific-memory/captures"
    variants = {
        ("body", "filters"): json.dumps({**capture, "filters": {"f": "__BAD__"}}),
        ("body", "items", 0, "structured_payload"): json.dumps(
            {**capture, "items": [{**item, "structured_payload": {"k": "__BAD__"}}]}
        ),
        ("body", "items", 0, "source", "locator"): json.dumps(
            {**capture, "items": [{**item, "source": {**item["source"], "locator": {"page": "__BAD__"}}}]}
        ),
    }
    for loc, text in variants.items():
        for bad in ('"\\ud800"', "NaN"):
            body = text.replace('"__BAD__"', bad).encode()
            detail = _assert_renderable_422(client.post(url, content=body, headers=KEYED))
            assert [tuple(error["loc"]) for error in detail] == [loc]
    listing = client.get(f"/api/research/projects/{project_id}/scientific-memory", headers=KEYED)
    assert listing.status_code == 200, listing.text
    assert client.post(url, json=capture, headers=KEYED).status_code == 201


@pytest.mark.parametrize("keyed", [True, False], ids=["api-key", "anonymous"])
def test_undecodable_text_body_is_422_on_representative_routes(client, keyed):
    # A non-JSON content type makes FastAPI echo the raw body bytes as the
    # error input; jsonable_encoder's strict bytes.decode() used to raise.
    project_id = _project(client)
    paths = [
        "/api/feedback",  # public, anonymous
        "/api/research/projects",
        f"/api/research/projects/{project_id}/notes",
        "/api/mission-control/owner/session",  # owner login
        "/api/constituent/subscribe",  # public
    ]
    headers = {**TEXT, "X-API-Key": API_KEY} if keyed else TEXT
    for path in paths:
        response = client.post(path, content=UNDECODABLE_BODY, headers=headers)
        if not keyed and path.startswith("/api/research/"):
            assert response.status_code == 401, (path, response.text)
            continue
        detail = _assert_renderable_422(response)
        assert detail == [
            {
                "type": "model_attributes_type",
                "loc": ["body"],
                "msg": "Input should be a valid dictionary or object to extract fields from",
                "input": "\ufffd\ufffd",
            }
        ], path


def test_undecodable_body_never_changes_the_status_of_any_body_route(client):
    """On every body route, undecodable bytes are answered exactly like valid UTF-8 text.

    Statuses that are not 422 here (401 without a key, 503 or a local-environment
    500 from a dependency that needs DATABASE_URL) happen before body
    validation and are the same for both bodies.
    """
    seen: set[tuple[str, str]] = set()
    differences = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.body_field is None:
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in sorted(route.methods):
            if (method, path) in seen:
                continue
            seen.add((method, path))
            for headers in (TEXT, {**TEXT, "X-API-Key": API_KEY}):
                valid = client.request(method, path, content=b"text", headers=headers)
                undecodable = client.request(method, path, content=UNDECODABLE_BODY, headers=headers)
                if undecodable.status_code != valid.status_code:
                    differences.append((method, path, "X-API-Key" in headers, valid.status_code, undecodable.status_code))
                elif undecodable.status_code == 422:
                    undecodable.content.decode("utf-8", errors="strict")
                    assert "\\xff" not in undecodable.text
                    assert undecodable.json()["detail"]
    assert len(seen) > 300
    assert differences == []


# --- byte compatibility for ordinary 422s --------------------------------------------


def _mini_app(handler) -> TestClient:
    mini = FastAPI()
    if handler is not None:
        mini.add_exception_handler(RequestValidationError, handler)

    @mini.post("/projects")
    def create(payload: ProjectCreate, limit: int = Query(25, ge=1, le=100)):
        return {"ok": True}

    @mini.get("/items/{item_id}")
    def item(item_id: int, status: str = Query(pattern="^(ACTIVE|PAUSED)$")):
        return {"ok": True}

    return TestClient(mini, raise_server_exceptions=False)


ORDINARY_REQUESTS = [
    ("POST", "/projects", {"json": {}}),
    ("POST", "/projects", {"json": {"title": ""}}),
    ("POST", "/projects", {"json": {"title": "x", "status": "DONE", "extra": [1, 2]}}),
    ("POST", "/projects", {"json": {"title": "Dracula éè \U0001f33a"}, "params": {"limit": "0"}}),
    ("POST", "/projects", {"content": b'{"title": ', "headers": JSON}),
    ("POST", "/projects", {"json": ["not", "an", "object"]}),
    ("POST", "/projects", {"content": "Dracula éè \U0001f33a".encode(), "headers": TEXT}),
    ("POST", "/projects", {"content": b"plain ascii", "headers": TEXT}),
    ("POST", "/projects", {"content": b"", "headers": TEXT}),
    ("POST", "/projects", {"json": {"title": "t" * (MAX_ECHOED_INPUT_CHARS - 20)}}),
    ("GET", "/items/abc", {"params": {"status": "NOPE"}}),
    ("GET", "/items/1", {}),
]


@pytest.mark.parametrize(("method", "url", "kwargs"), ORDINARY_REQUESTS)
def test_ordinary_422_is_byte_identical_to_fastapi_default(method, url, kwargs):
    default = _mini_app(None).request(method, url, **kwargs)
    ours = _mini_app(request_validation_exception_handler).request(method, url, **kwargs)
    assert default.status_code == ours.status_code == 422
    assert ours.content == default.content
    assert ours.headers["content-type"] == default.headers["content-type"]


def test_the_real_app_uses_the_renderable_handler():
    assert app.exception_handlers[RequestValidationError] is request_validation_exception_handler
    assert app.exception_handlers[RequestValidationError] is not fastapi_default_handler


def test_malformed_input_crashes_fastapis_default_handler_but_not_ours():
    # Documents the defect this module exists for.
    for body, headers in ((LONE_SURROGATE_BODY, JSON), (b'{"title": NaN}', JSON), (UNDECODABLE_BODY, TEXT)):
        default = _mini_app(None).post("/projects", content=body, headers=headers)
        assert default.status_code == 500
        _assert_renderable_422(_mini_app(request_validation_exception_handler).post("/projects", content=body, headers=headers))


def test_oversized_echoed_input_is_not_echoed():
    big = "t" * (MAX_ECHOED_INPUT_CHARS + 1)
    response = _mini_app(request_validation_exception_handler).post(
        "/projects", json={"title": "x", "extra": big, "nested": {"blob": big}}
    )
    detail = response.json()["detail"]
    assert response.status_code == 422 and big not in response.text
    assert [(e["type"], e["loc"], "input" in e) for e in detail] == [
        ("extra_forbidden", ["body", "extra"], False),
        ("extra_forbidden", ["body", "nested"], False),
    ]


def test_renderable_errors_sanitises_query_path_and_ctx_values():
    errors = [
        {"type": "string_pattern_mismatch", "loc": ("query", "q\ud800"), "msg": "m", "input": "a\udfffb", "ctx": {"pattern": "\ud800"}},
        {"type": "string_unicode", "loc": ("path", "id"), "msg": "m", "input": "\ud800"},
        {"type": "float_parsing", "loc": ("body", "x"), "msg": "m", "input": [float("nan"), float("inf"), float("-inf"), 1.5]},
    ]
    rendered = renderable_validation_errors(errors)
    assert rendered == [
        {"type": "string_pattern_mismatch", "loc": ["query", "q�"], "msg": "m", "input": "a�b", "ctx": {"pattern": "�"}},
        {"type": "string_unicode", "loc": ["path", "id"], "msg": "m"},
        {"type": "float_parsing", "loc": ["body", "x"], "msg": "m", "input": ["NaN", "Infinity", "-Infinity", 1.5]},
    ]
    json.dumps(rendered, ensure_ascii=False, allow_nan=False).encode("utf-8")


def test_renderable_errors_decodes_bytes_and_caps_them_like_strings():
    big = b"\xff" * (MAX_ECHOED_INPUT_CHARS + 1)
    errors = [
        {"type": "model_attributes_type", "loc": ("body",), "msg": "m", "input": b"ok \xc3\xa9"},
        {"type": "model_attributes_type", "loc": ("body",), "msg": "m", "input": b"a\xffb\xfe"},
        {"type": "t", "loc": ("body", "x"), "msg": "m", "input": {"k": [b"\x80"]}, "ctx": {"raw": (b"\xfe",)}},
        {"type": "model_attributes_type", "loc": ("body",), "msg": "m", "input": big},
    ]
    assert renderable_validation_errors(errors) == [
        {"type": "model_attributes_type", "loc": ["body"], "msg": "m", "input": "ok é"},
        {"type": "model_attributes_type", "loc": ["body"], "msg": "m", "input": "a\ufffdb\ufffd"},
        {"type": "t", "loc": ["body", "x"], "msg": "m", "input": {"k": ["\ufffd"]}, "ctx": {"raw": ["\ufffd"]}},
        {"type": "model_attributes_type", "loc": ["body"], "msg": "m"},
    ]
