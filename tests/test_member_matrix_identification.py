"""Release 1 journey 4: signed-in members run their own Matrix identification sessions.

Owner decisions (2026-09-26): Matrix identification is available to signed-in members;
sessions are private to the account that created them; candidate evidence internals
and owner tools stay owner-only.

Supabase is always mocked; these tests never reach the network.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import matrix_member_access, member_auth
from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
    list_registry_versions,
)
from runtime.matrix_identification_session import create_session, get_session

SUPABASE_GET = "app.university.learner_auth.requests.get"
MEMBER_A = "22222222-2222-2222-2222-222222222222"
MEMBER_B = "33333333-3333-3333-3333-333333333333"
PREFIX = "/api/matrix-identification"

# Exact (method, path) set opened to members. Anything else under the prefix stays
# owner-only and answers a verified member with 403 OWNER_ACCESS_REQUIRED.
EXPECTED_MEMBER_MATRIX_ROUTES = {
    ("GET", "/api/matrix-identification/registry"),
    ("GET", "/api/matrix-identification/registry/{registry_id}/{version}"),
    ("POST", "/api/matrix-identification/sessions"),
    ("GET", "/api/matrix-identification/sessions/{session_id}"),
    ("POST", "/api/matrix-identification/sessions/{session_id}/observations"),
    ("POST", "/api/matrix-identification/sessions/{session_id}/evaluate"),
    ("POST", "/api/matrix-identification/sessions/{session_id}/explain"),
}
EXPECTED_OWNER_ONLY_MATRIX_ROUTES = {
    ("GET", "/api/matrix-identification/contract"),
    ("POST", "/api/matrix-identification/evaluate"),
    ("GET", "/api/matrix-identification/persistence-readiness"),
    ("POST", "/api/matrix-identification/registry"),
    ("POST", "/api/matrix-identification/registry/evaluate"),
    (
        "GET",
        "/api/matrix-identification/registry/{registry_id}/{version}/concept-mapping-status",
    ),
    (
        "POST",
        "/api/matrix-identification/registry/{registry_id}/{version}/derive-concept-mappings",
    ),
    ("GET", "/api/matrix-identification/registry/persistence-status"),
    ("GET", "/api/matrix-identification/registry/persistence-preflight"),
    ("GET", "/api/matrix-identification/sessions/persistence-status"),
    ("GET", "/api/matrix-identification/sessions/persistence-preflight"),
    ("POST", "/api/matrix-identification/sessions/{session_id}/reports"),
    ("GET", "/api/matrix-identification/sessions/{session_id}/reports"),
    ("GET", "/api/matrix-identification/sessions/{session_id}/reports/{report_id}"),
    (
        "GET",
        "/api/matrix-identification/sessions/{session_id}/vision/images/{image_id}/analyses",
    ),
    (
        "POST",
        "/api/matrix-identification/sessions/{session_id}/vision/analyses/{analysis_id}/suggestions",
    ),
    ("GET", "/api/matrix-identification/sessions/{session_id}/vision/suggestions"),
    (
        "GET",
        "/api/matrix-identification/sessions/{session_id}/vision/suggestions/{suggestion_id}/region",
    ),
    (
        "POST",
        "/api/matrix-identification/sessions/{session_id}/vision/suggestions/{suggestion_id}/review",
    ),
}
OWNER_ACCESS_REQUIRED_BODY = {
    "detail": {
        "code": "OWNER_ACCESS_REQUIRED",
        "message": "This view is limited to owner access",
    }
}

# Values planted in owner-authored registry fields that must never reach a member.
REGISTRY_AUTHOR = "registry-author@owner.example"
PLANTED = (
    REGISTRY_AUTHOR,
    "PLANTED-LOCALITY",
    "PLANTED-COLLECTOR",
    "PLANTED-SPECIMEN",
    "PLANTED-REVIEWER",
    "PLANTED-SCOPE-SITE",
    "-18.91",
    "47.52",
)


def _jwt(sub: str = MEMBER_A, marker: str = "a") -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    payload = {"sub": sub, "exp": int(time.time() + 3600), "m": marker}
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(payload)}.sig"


def _supabase_user(user_id: str) -> Mock:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {
        "id": user_id,
        "email": f"{user_id[:4]}@member.example",
        "user_metadata": {"full_name": "Member Name"},
    }
    return response


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path: Path):
    for name in (
        "OC_MEMBER_READS_ENABLED",
        matrix_member_access.MATRIX_MEMBER_ENV,
        matrix_member_access.SESSIONS_PER_HOUR_ENV,
        matrix_member_access.WRITES_PER_MINUTE_ENV,
        "OC_SUPABASE_URL",
        "OC_SUPABASE_ANON_KEY",
        "OCU_SUPABASE_URL",
        "OCU_SUPABASE_ANON_KEY",
        "CALYX_MATRIX_SESSION_DURABLE_ENABLED",
        "CALYX_MATRIX_REGISTRY_DURABLE_ENABLED",
        "CALYX_CHAT_COMPLETIONS_URL",
        "CALYX_CHAT_MODEL",
        "CALYX_AGENT_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CALYX_API_KEY", "test-api-key")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-owner-secret")
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("CALYX_MATRIX_REGISTRY_DIR", str(tmp_path / "registry"))
    monkeypatch.setenv("CALYX_MATRIX_SESSION_DIR", str(tmp_path / "sessions"))
    member_auth.clear_member_token_cache()
    matrix_member_access.clear_member_matrix_limits()
    yield
    member_auth.clear_member_token_cache()
    matrix_member_access.clear_member_matrix_limits()


@pytest.fixture(autouse=True)
def registry(tmp_path: Path) -> dict:
    return create_registry_version(
        registry_id="angraecum-demo",
        version="1",
        title="Angraecum bounded diagnostic matrix",
        scope={"genus": "Angraecum", "site": "PLANTED-SCOPE-SITE", "latitude": -18.91},
        characters=[
            RegistryCharacter(
                "flower_color",
                "Flower color",
                description="Color of the open flower.",
                weight=1,
                provenance={"specimen": "PLANTED-SPECIMEN"},
            ),
            RegistryCharacter(
                "spur_length_mm", "Spur length", value_type="numeric_range", weight=3
            ),
            RegistryCharacter("flower_shape", "Flower shape", weight=1),
        ],
        candidates=[
            Candidate(
                "world-plants:angraecum-sesquipedale",
                "Angraecum sesquipedale",
                {
                    "flower_color": "white",
                    "spur_length_mm": {"min": 250, "max": 350},
                    "flower_shape": "star-shaped",
                },
                provenance={
                    "source": "curated diagnostic matrix",
                    "locality": "PLANTED-LOCALITY",
                    "collector": "PLANTED-COLLECTOR",
                    "decimalLongitude": 47.52,
                },
            ),
            Candidate(
                "world-plants:angraecum-eburneum",
                "Angraecum eburneum",
                {"flower_color": "white", "spur_length_mm": {"min": 80, "max": 150}},
                provenance={
                    "source": {"nested": "PLANTED-LOCALITY"},
                    "citation": "Flora fixture 2026",
                },
            ),
        ],
        provenance={
            "source": "test governed assertions",
            "reviewer": "PLANTED-REVIEWER",
        },
        actor=REGISTRY_AUTHOR,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def owner_token() -> str:
    return str(create_owner_session_token("owner")["token"])


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    def fake_get(url, headers=None, timeout=None):
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        if payload.get("m") == "invalid":
            return Mock(status_code=401, ok=False)
        return _supabase_user(payload["sub"])

    mock = Mock(side_effect=fake_get)
    monkeypatch.setattr(SUPABASE_GET, mock)
    return mock


def _member(sub: str = MEMBER_A, marker: str = "a") -> dict[str, str]:
    return _bearer(_jwt(sub, marker))


def _matrix_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PREFIX)
        for method in route.methods
        # The CORS preflight catch-all answers OPTIONS only; it serves no data.
        if method != "OPTIONS"
    }


def _concrete(path: str, session_id: str) -> str:
    values = {"session_id": session_id, "registry_id": "angraecum-demo", "version": "1"}
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), "1"), path)


def _flow(client: TestClient, headers: dict[str, str]) -> dict[str, dict]:
    listing = client.get(f"{PREFIX}/registry", headers=headers)
    assert listing.status_code == 200, listing.text
    detail = client.get(f"{PREFIX}/registry/angraecum-demo/1", headers=headers)
    assert detail.status_code == 200, detail.text
    created = client.post(
        f"{PREFIX}/sessions",
        headers=headers,
        json={
            "registry_id": "angraecum-demo",
            "version": "1",
            "metadata": {
                "input_mode": "guided",
                "client": "orchid-continuum-frontend",
                "actor": "owner",
            },
        },
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    first = client.post(
        f"{PREFIX}/sessions/{session_id}/evaluate", headers=headers, json={"limit": 20}
    )
    assert first.status_code == 200, first.text
    observed = client.post(
        f"{PREFIX}/sessions/{session_id}/observations",
        headers=headers,
        json={
            "character": "spur_length_mm",
            "value": 300,
            "certainty": "probable",
            "source": {
                "kind": "vision_review",
                "interface": "guided-identification",
                "gps": "PLANTED-LOCALITY",
            },
        },
    )
    assert observed.status_code == 200, observed.text
    evaluated = client.post(
        f"{PREFIX}/sessions/{session_id}/evaluate", headers=headers, json={"limit": 20}
    )
    assert evaluated.status_code == 200, evaluated.text
    explained = client.post(
        f"{PREFIX}/sessions/{session_id}/explain",
        headers=headers,
        json={"audience": "beginner", "focus": "candidate_comparison"},
    )
    assert explained.status_code == 200, explained.text
    read = client.get(f"{PREFIX}/sessions/{session_id}", headers=headers)
    assert read.status_code == 200, read.text
    return {
        "listing": listing.json(),
        "detail": detail.json(),
        "created": created.json(),
        "first": first.json(),
        "observed": observed.json(),
        "evaluated": evaluated.json(),
        "explained": explained.json(),
        "read": read.json(),
        "session_id": session_id,
    }


# --- declared surface -----------------------------------------------------------------


def test_route_enumeration_matches_the_declared_member_matrix_surface():
    routes = _matrix_routes()
    marked = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PREFIX)
        for method in route.methods
        if getattr(route.endpoint, matrix_member_access.MATRIX_MEMBER_ATTR, None)
    }
    preflight = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith(PREFIX)
        and "OPTIONS" in route.methods
    }
    assert preflight == {"/api/matrix-identification/{full_path:path}"}
    assert marked == EXPECTED_MEMBER_MATRIX_ROUTES
    assert routes == EXPECTED_MEMBER_MATRIX_ROUTES | EXPECTED_OWNER_ONLY_MATRIX_ROUTES
    assert not EXPECTED_MEMBER_MATRIX_ROUTES & EXPECTED_OWNER_ONLY_MATRIX_ROUTES
    # Every matrix-identification data route is gated by the default-deny dependency.
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path.startswith(PREFIX)
            and "OPTIONS" not in route.methods
        ):
            calls = {dep.call for dep in route.dependant.dependencies}
            assert matrix_member_access.owner_or_matrix_member in calls, route.path


def test_every_matrix_route_enforces_member_owner_and_anonymous_rules(
    client, owner_token, supabase
):
    session_id = client.post(
        f"{PREFIX}/sessions",
        headers=_member(),
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    failures = []
    for method, path in sorted(_matrix_routes()):
        url = _concrete(path, session_id)
        member = client.request(method, url, headers=_member(), json={})
        owner = client.request(method, url, headers=_bearer(owner_token), json={})
        anonymous = client.request(method, url, json={})
        invalid = client.request(
            method, url, headers=_member(marker="invalid"), json={}
        )
        if (method, path) in EXPECTED_MEMBER_MATRIX_ROUTES:
            if member.status_code in {401, 403}:
                failures.append(("member rejected", method, path, member.status_code))
        elif member.status_code != 403 or member.json() != OWNER_ACCESS_REQUIRED_BODY:
            failures.append(
                (
                    "member not 403 OWNER_ACCESS_REQUIRED",
                    method,
                    path,
                    member.status_code,
                )
            )
        if owner.status_code in {401, 403}:
            failures.append(("owner rejected", method, path, owner.status_code))
        if anonymous.status_code != 401:
            failures.append(("anonymous admitted", method, path, anonymous.status_code))
        if invalid.status_code != 401:
            failures.append(
                ("invalid member token not 401", method, path, invalid.status_code)
            )
    assert not failures, failures


def test_owner_only_403_precedes_validation_and_never_discloses_existence(
    client, supabase
):
    real = client.post(
        f"{PREFIX}/sessions",
        headers=_member(),
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    missing = str(uuid.uuid4())
    urls = [
        ("GET", f"{PREFIX}/sessions/{real}/reports"),
        ("GET", f"{PREFIX}/sessions/{missing}/reports"),
        ("POST", f"{PREFIX}/sessions/{real}/reports"),
        ("GET", f"{PREFIX}/sessions/{real}/vision/suggestions"),
        ("GET", f"{PREFIX}/sessions/not-a-uuid/vision/suggestions"),
        ("GET", f"{PREFIX}/registry/angraecum-demo/1/concept-mapping-status"),
        ("GET", f"{PREFIX}/registry/nope/9/concept-mapping-status"),
        ("POST", f"{PREFIX}/registry"),
        ("POST", f"{PREFIX}/registry/evaluate"),
        ("POST", f"{PREFIX}/evaluate"),
        ("GET", f"{PREFIX}/sessions/persistence-status"),
    ]
    bodies = set()
    for method, url in urls:
        response = client.request(method, url, headers=_member(), json={"not": "valid"})
        assert response.status_code == 403, (method, url, response.status_code)
        bodies.add(response.content)
    assert bodies == {
        json.dumps(OWNER_ACCESS_REQUIRED_BODY, separators=(",", ":")).encode()
    }


# --- member identify flow ---------------------------------------------------------------


def test_member_full_identify_flow(client, supabase):
    flow = _flow(client, _member())
    listing = flow["listing"]["versions"]
    assert [(v["registry_id"], v["version"]) for v in listing] == [
        ("angraecum-demo", "1")
    ]
    assert set(listing[0]) == {
        "registry_id",
        "version",
        "title",
        "scope",
        "candidate_count",
        "character_count",
        "created_at",
        "checksum_sha256",
        "publication_state",
    }
    assert listing[0]["scope"] == {"genus": "Angraecum"}
    detail = flow["detail"]
    assert [c["character"] for c in detail["characters"]] == [
        "flower_color",
        "spur_length_mm",
        "flower_shape",
    ]
    assert (
        "candidates" not in detail
        and "provenance" not in detail
        and "created_by" not in detail
    )
    assert all("provenance" not in c for c in detail["characters"])

    created = flow["created"]
    assert (
        created["mine"] is True and "actor" not in created and "metadata" not in created
    )
    report = flow["evaluated"]["report"]
    assert report["observation_count"] == 1
    top = report["candidates"][0]
    assert top["scientific_name"] == "Angraecum sesquipedale"
    assert top["explanations"][0]["status"] == "matched"
    assert top["provenance"] == {"source": "curated diagnostic matrix"}
    assert report["candidates"][1]["provenance"] == {"citation": "Flora fixture 2026"}
    assert (
        report["registry"]["checksum_sha256"] == created["registry"]["checksum_sha256"]
    )
    session = flow["evaluated"]["session"]
    assert session["observations"][0]["source"] == {
        "kind": "user_observation",
        "interface": "guided-identification",
    }
    assert "recorded_by" not in session["observations"][0]
    assert flow["first"]["next_observation"]["character"] == "spur_length_mm"
    assert set(flow["first"]["next_observation"]) <= {
        "character",
        "label",
        "description",
        "value_type",
        "concept_id",
        "matrix_weight",
        "candidate_coverage",
        "distinct_state_count",
        "candidate_count",
        "selection_score",
        "reason_code",
        "explanation_boundary",
    }
    assert flow["evaluated"]["next_observation"] is None

    explained = flow["explained"]
    assert explained["narrative"]["provider"] == "matrix-deterministic-governed"
    assert (
        explained["evidence"]["candidate_order"][0]
        == "world-plants:angraecum-sesquipedale"
    )
    assert flow["read"]["revision"] == 1 and flow["read"]["mine"] is True


def test_member_session_is_bound_to_the_verified_subject_server_side(client, supabase):
    flow = _flow(client, _member())
    stored = get_session(flow["session_id"])
    assert stored["actor"] == f"supabase:{MEMBER_A}"
    assert stored["metadata"] == {
        "input_mode": "guided",
        "client": "orchid-continuum-frontend",
    }
    assert stored["observations"][0]["recorded_by"] == f"supabase:{MEMBER_A}"
    assert stored["observations"][0]["source"] == {
        "kind": "user_observation",
        "interface": "guided-identification",
    }


def test_no_account_identifier_or_owner_internals_reach_a_member(client, supabase):
    flow = _flow(client, _member())
    text = json.dumps({k: v for k, v in flow.items() if k != "session_id"})
    for needle in (
        *PLANTED,
        MEMBER_A,
        "supabase:",
        "owner",
        "recorded_by",
        "created_by",
        '"actor"',
        "member.example",
    ):
        assert needle not in text, needle


def test_other_member_gets_404_for_every_session_route(client, supabase):
    session_id = _flow(client, _member(MEMBER_A))["session_id"]
    other = _member(MEMBER_B, marker="b")
    missing = str(uuid.uuid4())
    for sid in (session_id, missing):
        responses = [
            client.get(f"{PREFIX}/sessions/{sid}", headers=other),
            client.post(
                f"{PREFIX}/sessions/{sid}/observations",
                headers=other,
                json={"character": "flower_color", "value": "white"},
            ),
            client.post(f"{PREFIX}/sessions/{sid}/evaluate", headers=other, json={}),
            client.post(f"{PREFIX}/sessions/{sid}/explain", headers=other, json={}),
        ]
        assert [r.status_code for r in responses] == [404, 404, 404, 404]
        assert {r.json()["detail"] for r in responses} == {
            f"identification session not found: {sid}"
        }
    # Member A's session is untouched by B's attempts.
    assert get_session(session_id)["revision"] == 1
    assert client.get(f"{PREFIX}/sessions/not-a-uuid", headers=other).status_code == 404


def test_owner_sessions_stay_owner_accessible_and_invisible_to_members(
    client, owner_token, supabase
):
    owner_session = create_session(
        registry_id="angraecum-demo", version="1", actor="owner"
    )
    sid = owner_session["session_id"]
    assert client.get(f"{PREFIX}/sessions/{sid}", headers=_member()).status_code == 404
    assert (
        client.post(
            f"{PREFIX}/sessions/{sid}/evaluate", headers=_member(), json={}
        ).status_code
        == 404
    )
    response = client.get(f"{PREFIX}/sessions/{sid}", headers=_bearer(owner_token))
    assert response.status_code == 200 and response.json()["actor"] == "owner"
    # API-key automation keeps cross-tenant access, as before.
    member_sid = _flow(client, _member())["session_id"]
    api = client.get(
        f"{PREFIX}/sessions/{member_sid}", headers={"X-API-Key": "test-api-key"}
    )
    assert api.status_code == 200 and api.json()["actor"] == f"supabase:{MEMBER_A}"


def test_owner_and_api_key_responses_are_the_unmodified_runtime_output(
    client, owner_token, supabase
):
    for headers in (_bearer(owner_token), {"X-API-Key": "test-api-key"}):
        listing = client.get(f"{PREFIX}/registry", headers=headers)
        assert listing.json() == {
            "versions": list_registry_versions(),
            "read_only_listing": True,
        }
        assert listing.json()["versions"][0]["created_by"] == REGISTRY_AUTHOR
        detail = client.get(
            f"{PREFIX}/registry/angraecum-demo/1", headers=headers
        ).json()
        assert detail["candidates"][0]["provenance"]["locality"] == "PLANTED-LOCALITY"
    created = client.post(
        f"{PREFIX}/sessions",
        headers=_bearer(owner_token),
        json={
            "registry_id": "angraecum-demo",
            "version": "1",
            "metadata": {"free": "form"},
        },
    )
    sid = created.json()["session_id"]
    assert created.json()["actor"] == "owner" and created.json()["metadata"] == {
        "free": "form"
    }
    raw = client.get(f"{PREFIX}/sessions/{sid}", headers=_bearer(owner_token))
    assert raw.json() == get_session(sid, access_actor="owner")
    observed = client.post(
        f"{PREFIX}/sessions/{sid}/observations",
        headers=_bearer(owner_token),
        json={
            "character": "flower_color",
            "value": "white",
            "source": {"kind": "vision_review"},
        },
    ).json()
    assert observed["observations"][0]["source"] == {"kind": "vision_review"}
    evaluated = client.post(
        f"{PREFIX}/sessions/{sid}/evaluate", headers=_bearer(owner_token), json={}
    ).json()
    assert evaluated["session"]["actor"] == "owner"
    assert any(
        (c["provenance"] or {}).get("collector") == "PLANTED-COLLECTOR"
        for c in evaluated["report"]["candidates"]
    )
    supabase.assert_not_called()


# --- availability and switches -------------------------------------------------------


def test_supabase_down_is_503_for_members_and_owner_is_unaffected(
    client, owner_token, supabase
):
    supabase.side_effect = requests.ConnectionError("down")
    member = client.get(f"{PREFIX}/registry", headers=_member(marker="down"))
    assert member.status_code == 503
    assert member.json()["detail"]["code"] == "MEMBER_AUTH_UNAVAILABLE"
    created = client.post(
        f"{PREFIX}/sessions",
        headers=_member(marker="down2"),
        json={"registry_id": "angraecum-demo", "version": "1"},
    )
    assert created.status_code == 503
    client.cookies.set(OWNER_SESSION_COOKIE, owner_token)
    assert client.get(f"{PREFIX}/registry").status_code == 200
    client.cookies.clear()
    assert (
        client.get(f"{PREFIX}/registry", headers=_bearer(owner_token)).status_code
        == 200
    )


def test_matrix_member_switch_restores_owner_only(
    client, owner_token, supabase, monkeypatch
):
    monkeypatch.setenv(matrix_member_access.MATRIX_MEMBER_ENV, "false")
    response = client.get(f"{PREFIX}/registry", headers=_member())
    assert response.status_code == 403 and response.json() == OWNER_ACCESS_REQUIRED_BODY
    assert (
        client.get(f"{PREFIX}/registry", headers=_bearer(owner_token)).status_code
        == 200
    )
    monkeypatch.delenv(matrix_member_access.MATRIX_MEMBER_ENV)
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    assert (
        client.get(f"{PREFIX}/registry", headers=_member(marker="c")).status_code == 401
    )
    assert (
        client.get(f"{PREFIX}/registry", headers=_bearer(owner_token)).status_code
        == 200
    )


def test_matrix_member_switch_defaults_enabled(monkeypatch):
    assert matrix_member_access.matrix_members_enabled() is True
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv(matrix_member_access.MATRIX_MEMBER_ENV, value)
        assert matrix_member_access.matrix_members_enabled() is True
    for value in ("0", "false", "off", ""):
        monkeypatch.setenv(matrix_member_access.MATRIX_MEMBER_ENV, value)
        assert matrix_member_access.matrix_members_enabled() is False


# --- limits ----------------------------------------------------------------------------


def test_member_payload_is_bounded(client, owner_token, supabase):
    big = {
        "registry_id": "angraecum-demo",
        "version": "1",
        "metadata": {"pad": "x" * 20000},
    }
    response = client.post(f"{PREFIX}/sessions", headers=_member(), json=big)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "MATRIX_MEMBER_PAYLOAD_TOO_LARGE"
    assert (
        client.post(
            f"{PREFIX}/sessions", headers=_bearer(owner_token), json=big
        ).status_code
        == 200
    )


def test_member_session_creation_is_rate_limited_per_account(
    client, owner_token, supabase, monkeypatch
):
    monkeypatch.setenv(matrix_member_access.SESSIONS_PER_HOUR_ENV, "2")
    body = {"registry_id": "angraecum-demo", "version": "1"}
    statuses = [
        client.post(f"{PREFIX}/sessions", headers=_member(), json=body).status_code
        for _ in range(3)
    ]
    assert statuses == [200, 200, 429]
    limited = client.post(f"{PREFIX}/sessions", headers=_member(), json=body)
    assert limited.json()["detail"]["code"] == "MATRIX_MEMBER_RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1
    # Another account and the owner are unaffected.
    assert (
        client.post(
            f"{PREFIX}/sessions", headers=_member(MEMBER_B, "b"), json=body
        ).status_code
        == 200
    )
    for _ in range(3):
        assert (
            client.post(
                f"{PREFIX}/sessions", headers=_bearer(owner_token), json=body
            ).status_code
            == 200
        )


def test_member_session_writes_are_rate_limited(client, supabase, monkeypatch):
    monkeypatch.setenv(matrix_member_access.WRITES_PER_MINUTE_ENV, "2")
    sid = client.post(
        f"{PREFIX}/sessions",
        headers=_member(),
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    statuses = [
        client.post(
            f"{PREFIX}/sessions/{sid}/evaluate", headers=_member(), json={}
        ).status_code
        for _ in range(3)
    ]
    assert statuses == [200, 200, 429]
    assert client.get(f"{PREFIX}/sessions/{sid}", headers=_member()).status_code == 200


def test_member_observations_per_session_are_capped(client, supabase, monkeypatch):
    monkeypatch.setattr(
        "app.routers.matrix_identification_session.MEMBER_MAX_OBSERVATIONS_PER_SESSION",
        2,
    )
    sid = client.post(
        f"{PREFIX}/sessions",
        headers=_member(),
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    body = {"character": "flower_color", "value": "white"}
    statuses = [
        client.post(
            f"{PREFIX}/sessions/{sid}/observations", headers=_member(), json=body
        ).status_code
        for _ in range(3)
    ]
    assert statuses == [200, 200, 409]


def test_member_explanation_never_reaches_a_configured_provider(
    client, supabase, monkeypatch
):
    def forbidden():
        raise AssertionError(
            "member explanation must not resolve the configured provider"
        )

    monkeypatch.setattr(
        "runtime.matrix_identification_explanation.configured_reply_provider", forbidden
    )
    sid = client.post(
        f"{PREFIX}/sessions",
        headers=_member(),
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    response = client.post(
        f"{PREFIX}/sessions/{sid}/explain", headers=_member(), json={}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["narrative"]["provider"] == "matrix-deterministic-governed"
    assert payload["narrative"]["fallback_error"] is None
    # The digest describes exactly the member-shaped evidence that was returned.
    from runtime.matrix_identification_explanation import _digest

    evidence = dict(payload["evidence"])
    digest = evidence.pop("evidence_digest_sha256")
    assert digest == _digest(evidence)
