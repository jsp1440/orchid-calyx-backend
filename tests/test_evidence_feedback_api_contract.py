"""Pins the product's evidence-feedback HTTP contract (Journey 12).

The frontend client ``src/lib/evidenceFeedback.ts`` (orchid-continuum-frontend,
``oc-autonomous-integration``) builds every request from
``${CALYX_BACKEND_BASE_URL}/api/evidence-feedback`` with
``credentials: 'include'``. These tests drive the real ``app.main`` application
with real owner/API-key authentication (no dependency overrides) using the
frontend's exact paths and request bodies.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import member_auth
from app.evidence_feedback import (
    EvidenceFeedbackService,
    FileEvidenceFeedbackRepository,
    ObjectType,
)
from app.evidence_feedback.repository import EvidenceFeedbackRepositoryError
from app.main import app
from app.security import OWNER_SESSION_COOKIE, verify_owner_or_api_key

TEST_API_KEY = "local-test-api-key-not-a-credential"
TEST_OWNER_CODE = "local-test-owner-code-not-a-credential"
TEST_SESSION_SECRET = "local-test-session-secret-not-a-credential"

# Exact paths the frontend calls (src/lib/evidenceFeedback.ts).
FRONTEND_BASE = "/api/evidence-feedback"
FRONTEND_ROUTES = {
    ("POST", f"{FRONTEND_BASE}/objects"),
    ("POST", f"{FRONTEND_BASE}/cases"),
    ("GET", f"{FRONTEND_BASE}/cases/{{case_id}}"),
}
# Backend-only reviewer route; not called by the frontend.
REVIEWER_ROUTES = {("POST", f"{FRONTEND_BASE}/cases/{{case_id}}/accept-trivial")}
# Whole-application member-readable surface (see test_member_read_access.py).
MEMBER_READABLE_ROUTES = {
    ("GET", "/api/research/traits"),
    ("GET", "/api/literature-extraction/papers"),
    ("GET", "/api/evidence-aggregation/health"),
    ("GET", "/api/evidence-aggregation/registry"),
}

# Field sets required by the frontend TypeScript interfaces.
OBJECT_VERSION_FIELDS = {
    "object_id",
    "object_type",
    "version_hash",
    "payload",
    "created_at",
    "previous_version_hash",
}
CASE_FIELDS = {
    "case_id",
    "object_id",
    "object_version_hash",
    "object_type",
    "page_context",
    "feedback_class",
    "statement",
    "disposition",
    "status",
    "review_lane",
    "created_at",
    "updated_at",
    "proposed_replacement",
    "citation",
    "resolution",
    "resulting_version_hash",
}
STATUS_FIELDS = {
    "case_id",
    "status",
    "disposition",
    "resolution",
    "resulting_version_hash",
}
FRONTEND_CASE_STATUSES = {"submitted", "pending_review", "resolved"}


def _feedback_routes() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in app.routes
        if isinstance(route, APIRoute) and "evidence-feedback" in route.path
        for method in route.methods
    }


def _dependency_calls(route: APIRoute) -> set:
    calls, stack = set(), list(route.dependant.dependencies)
    while stack:
        dependant = stack.pop()
        calls.add(dependant.call)
        stack.extend(dependant.dependencies)
    return calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CALYX_EVIDENCE_FEEDBACK_ROOT", str(tmp_path / "feedback"))
    monkeypatch.setenv("CALYX_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", TEST_OWNER_CODE)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("CALYX_OWNER_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    return TestClient(app)


def _owner_login(client: TestClient) -> None:
    response = client.post(
        "/api/mission-control/owner/session",
        json={"access_code": TEST_OWNER_CODE},
    )
    assert response.status_code == 200
    # The owner cookie is scoped to /api/; the browser sends it only below it.
    cookie = next(c for c in client.cookies.jar if c.name == OWNER_SESSION_COOKIE)
    assert cookie.path == "/api/"


def _frontend_register(client: TestClient, payload: dict, **kwargs):
    # registerEvidenceObject(): body { object_id, object_type, payload }
    return client.post(
        f"{FRONTEND_BASE}/objects",
        json={"object_id": "lexicon:labellum", "object_type": "lexicon", "payload": payload},
        **kwargs,
    )


def _frontend_case_body(version_hash: str, statement: str) -> dict:
    # submitEvidenceFeedback(): exact body the frontend serializes, including
    # explicit nulls for blank optional fields and severity 'normal'.
    return {
        "object_id": "lexicon:labellum",
        "object_version_hash": version_hash,
        "object_type": "lexicon",
        "page_context": "/lexicon/labellum",
        "feedback_class": "report_problem",
        "statement": statement,
        "proposed_replacement": None,
        "citation": None,
        "source_partner_id": None,
        "defect_kind": None,
        "severity": "normal",
    }


def test_route_surface_matches_frontend_paths_and_stays_owner_or_api_key_only():
    routes = _feedback_routes()
    assert set(routes) == FRONTEND_ROUTES | REVIEWER_ROUTES
    assert not any(path.startswith("/evidence-feedback") for _, path in routes)
    for key, route in routes.items():
        assert verify_owner_or_api_key in _dependency_calls(route), key
        assert not getattr(route.endpoint, member_auth.MEMBER_READABLE_ATTR, False), key
    member_readable = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        and getattr(route.endpoint, member_auth.MEMBER_READABLE_ATTR, False)
        for method in route.methods
    }
    assert member_readable == MEMBER_READABLE_ROUTES


def test_owner_session_submits_frontend_request_shape_end_to_end(client):
    _owner_login(client)
    displayed = {"term": "labellum", "definition": "a modified petel"}

    registered = _frontend_register(client, displayed)
    assert registered.status_code == 201
    version = registered.json()
    assert OBJECT_VERSION_FIELDS <= set(version)

    submitted = client.post(
        f"{FRONTEND_BASE}/cases",
        json=_frontend_case_body(version["version_hash"], "Petal is misspelled."),
    )
    assert submitted.status_code == 201
    body = submitted.json()
    assert body["created"] is True
    assert body["duplicate_of"] is None
    case = body["case"]
    assert CASE_FIELDS <= set(case)
    assert case["status"] in FRONTEND_CASE_STATUSES
    assert case["object_version_hash"] == version["version_hash"]

    status = client.get(f"{FRONTEND_BASE}/cases/{case['case_id']}")
    assert status.status_code == 200
    assert set(status.json()) == STATUS_FIELDS
    assert status.json()["case_id"] == case["case_id"]


def test_second_feedback_on_same_displayed_record_is_accepted(client):
    """The frontend re-registers the displayed version before every submission."""

    _owner_login(client)
    displayed = {"term": "column", "definition": "fused reproductive structure"}
    first = _frontend_register(client, displayed)
    again = _frontend_register(client, displayed)
    assert first.status_code == 201
    assert again.status_code == 201
    assert again.json() == first.json()

    one = client.post(
        f"{FRONTEND_BASE}/cases",
        json=_frontend_case_body(first.json()["version_hash"], "Needs a citation."),
    )
    other = client.post(
        f"{FRONTEND_BASE}/cases",
        json=_frontend_case_body(again.json()["version_hash"], "Spelling differs from source."),
    )
    repeat = client.post(
        f"{FRONTEND_BASE}/cases",
        json=_frontend_case_body(first.json()["version_hash"], "Needs a citation."),
    )
    assert one.status_code == other.status_code == repeat.status_code == 201
    assert other.json()["created"] is True
    assert repeat.json()["created"] is False
    assert repeat.json()["duplicate_of"] == one.json()["case"]["case_id"]


def test_api_key_submits_and_non_owner_callers_are_rejected(client):
    ok = _frontend_register(client, {"definition": "x"}, headers={"X-API-Key": TEST_API_KEY})
    assert ok.status_code == 201

    anonymous = _frontend_register(client, {"definition": "x"})
    wrong_key = _frontend_register(client, {"definition": "x"}, headers={"X-API-Key": "wrong"})
    member_bearer = _frontend_register(
        client,
        {"definition": "x"},
        headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJtZW1iZXIifQ.sig"},
    )
    anonymous_status = client.get(f"{FRONTEND_BASE}/cases/efc-anything")
    assert anonymous.status_code == 401
    assert wrong_key.status_code == 401
    assert member_bearer.status_code == 401
    assert anonymous_status.status_code == 401


def test_old_unprefixed_path_is_not_served(client):
    response = client.post(
        "/evidence-feedback/objects",
        json={"object_id": "lexicon:x", "object_type": "lexicon", "payload": {}},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert response.status_code == 404


def test_reregistration_keeps_original_record_and_rejects_conflicting_lineage(tmp_path):
    clock_values = iter(["2026-09-20T20:00:00+00:00", "2026-09-21T09:00:00+00:00"])
    service = EvidenceFeedbackService(
        FileEvidenceFeedbackRepository(tmp_path),
        clock=lambda: next(clock_values, "2026-09-22T00:00:00+00:00"),
    )
    base = service.register_object(
        object_id="lexicon:sepal", object_type=ObjectType.LEXICON, payload={"d": "a"}
    )
    again = service.register_object(
        object_id="lexicon:sepal", object_type=ObjectType.LEXICON, payload={"d": "a"}
    )
    assert again == base
    assert again.created_at == "2026-09-20T20:00:00+00:00"

    other = service.register_object(
        object_id="lexicon:sepal", object_type=ObjectType.LEXICON, payload={"d": "b"}
    )
    with pytest.raises(EvidenceFeedbackRepositoryError, match="IMMUTABILITY_VIOLATION"):
        service.register_object(
            object_id="lexicon:sepal",
            object_type=ObjectType.LEXICON,
            payload={"d": "a"},
            previous_version_hash=other.version_hash,
        )
    with pytest.raises(EvidenceFeedbackRepositoryError, match="IMMUTABILITY_VIOLATION"):
        service.register_object(
            object_id="lexicon:sepal", object_type=ObjectType.TAXONOMY, payload={"d": "a"}
        )
