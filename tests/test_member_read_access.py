"""Member read access: owner decision 2026-09-26, read-only GET product endpoints.

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

from app import member_auth
from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

SUPABASE_GET = "app.university.learner_auth.requests.get"
MEMBER_UUID = "22222222-2222-2222-2222-222222222222"
PREFIXES = (
    "/api/research/traits",
    "/api/candidate-knowledge",
    "/api/evidence-aggregation",
    "/api/literature-extraction",
)
# Exact (method, path) set opened to members. Anything not listed stays owner-only.
EXPECTED_MEMBER_READS = {
    ("GET", "/api/research/traits"),
    ("GET", "/api/candidate-knowledge/runs/{run_id}"),
    ("GET", "/api/candidate-knowledge/runs"),
    ("GET", "/api/candidate-knowledge/candidates"),
    ("GET", "/api/candidate-knowledge/reviews"),
    ("GET", "/api/candidate-knowledge/duplicates"),
    ("GET", "/api/candidate-knowledge/conflicts"),
    ("GET", "/api/candidate-knowledge/tombstones"),
    ("GET", "/api/candidate-knowledge/health"),
    ("GET", "/api/evidence-aggregation/runs/{rid}"),
    ("GET", "/api/evidence-aggregation/runs"),
    ("GET", "/api/evidence-aggregation/runs/{rid}/items"),
    ("GET", "/api/evidence-aggregation/clusters"),
    ("GET", "/api/evidence-aggregation/clusters/{cid}"),
    ("GET", "/api/evidence-aggregation/aggregates"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}/versions"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}/summary"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}/support-network"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}/contradiction-network"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}/source-independence"),
    ("GET", "/api/evidence-aggregation/aggregates/{aid}/{dimension}"),
    ("GET", "/api/evidence-aggregation/conflicts"),
    ("GET", "/api/evidence-aggregation/reviews"),
    ("GET", "/api/evidence-aggregation/export"),
    ("GET", "/api/evidence-aggregation/registry"),
    ("GET", "/api/evidence-aggregation/tombstones"),
    ("GET", "/api/evidence-aggregation/health"),
    ("GET", "/api/literature-extraction/papers"),
    ("GET", "/api/literature-extraction/papers/{paper_id}/source-binding"),
}
# GET routes deliberately left owner-only (unredacted licensed text, raw DB errors).
EXPECTED_OWNER_ONLY_READS = {
    ("GET", "/api/candidate-knowledge/candidates/{candidate_id}"),
    ("GET", "/api/candidate-knowledge/runs/{run_id}/items"),
    ("GET", "/api/literature-extraction/papers/{paper_id}"),
    ("GET", "/api/literature-extraction/coverage-audit"),
}


def _jwt(sub: str = MEMBER_UUID, exp_offset: float = 3600, marker: str = "a") -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc({'sub': sub, 'exp': int(time.time() + exp_offset), 'm': marker})}.sig"


def _supabase_ok(user_id: str = MEMBER_UUID) -> Mock:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {
        "id": user_id,
        "email": "member@example.org",
        "user_metadata": {"full_name": "Member Name"},
    }
    return response


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (
        "OC_MEMBER_READS_ENABLED",
        "OC_SUPABASE_URL",
        "OC_SUPABASE_ANON_KEY",
        "OCU_SUPABASE_URL",
        "OCU_SUPABASE_ANON_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CALYX_API_KEY", "test-api-key")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-owner-secret")
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    member_auth.clear_member_token_cache()
    yield
    member_auth.clear_member_token_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def owner_token() -> str:
    return str(create_owner_session_token("owner")["token"])


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    mock = Mock(return_value=_supabase_ok())
    monkeypatch.setattr(SUPABASE_GET, mock)
    return mock


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


READ_URL = "/api/research/traits?genus=Dracula"
TRAITS_PAYLOAD = {"rank": "genus", "name": "Dracula", "traits": [{"state": "UNKNOWN"}]}


@pytest.fixture(autouse=True)
def _traits_stub(monkeypatch):
    from app.research_traits import routes as traits_routes

    monkeypatch.setattr(traits_routes, "get_service", lambda: Mock(get=Mock(return_value=TRAITS_PAYLOAD)))


# --- credential paths ---------------------------------------------------------------


def test_owner_cookie_reads(client, owner_token, supabase):
    client.cookies.set(OWNER_SESSION_COOKIE, owner_token)
    assert client.get(READ_URL).status_code == 200
    supabase.assert_not_called()


def test_owner_bearer_reads_and_is_never_sent_to_supabase(client, owner_token, supabase):
    assert client.get(READ_URL, headers=_bearer(owner_token)).status_code == 200
    supabase.assert_not_called()


def test_invalid_or_expired_owner_shaped_bearer_is_not_forwarded(client, owner_token, supabase, monkeypatch):
    forged = owner_token.split(".")[0] + "." + "0" * 64
    response = client.get(READ_URL, headers=_bearer(forged))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid owner session"
    expired = str(create_owner_session_token("owner", ttl_seconds=1)["token"])
    monkeypatch.setattr(time, "time", lambda: 10**12)
    response = client.get(READ_URL, headers=_bearer(expired))
    assert response.status_code == 401
    supabase.assert_not_called()


def test_api_key_reads(client, supabase):
    assert client.get(READ_URL, headers={"X-API-Key": "test-api-key"}).status_code == 200
    assert client.get(READ_URL, headers={"X-API-Key": "wrong"}).status_code == 401
    supabase.assert_not_called()


def test_valid_member_token_reads(client, supabase):
    token = _jwt()
    response = client.get(READ_URL, headers=_bearer(token))
    assert response.status_code == 200
    supabase.assert_called_once()
    headers = supabase.call_args.kwargs["headers"]
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["apikey"] == "anon-key"
    assert supabase.call_args.args[0] == "https://project.supabase.co/auth/v1/user"


def test_member_principal_exposes_no_token_email_or_profile(supabase):
    token = _jwt()
    principal = member_auth.verify_member_access_token(token)
    assert principal == {
        "actor": f"supabase:{MEMBER_UUID}",
        "subject": f"supabase:{MEMBER_UUID}",
        "auth_type": "supabase_member",
        "role": "member",
    }
    assert token not in json.dumps(principal)
    assert "member@example.org" not in json.dumps(principal)


def test_invalid_member_token_is_401(client, supabase):
    supabase.return_value = Mock(status_code=401, ok=False)
    response = client.get(READ_URL, headers=_bearer(_jwt()))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_MEMBER_TOKEN"


def test_missing_credentials_is_401(client, supabase):
    response = client.get(READ_URL)
    assert response.status_code == 401
    assert response.json()["detail"] == "Owner session, member session, or API key is required"
    assert client.get(READ_URL, headers={"Authorization": "Basic abc"}).status_code == 401
    supabase.assert_not_called()


def test_not_configured_member_503_owner_still_reads(client, owner_token, supabase, monkeypatch):
    monkeypatch.delenv("OC_SUPABASE_URL")
    monkeypatch.delenv("OC_SUPABASE_ANON_KEY")
    response = client.get(READ_URL, headers=_bearer(_jwt()))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MEMBER_AUTH_NOT_CONFIGURED"
    assert client.get(READ_URL, headers=_bearer(owner_token)).status_code == 200
    assert client.get(READ_URL, headers={"X-API-Key": "test-api-key"}).status_code == 200
    supabase.assert_not_called()


def test_neutral_env_falls_back_to_university_supabase_vars(client, supabase, monkeypatch):
    monkeypatch.delenv("OC_SUPABASE_URL")
    monkeypatch.delenv("OC_SUPABASE_ANON_KEY")
    monkeypatch.setenv("OCU_SUPABASE_URL", "https://learner.supabase.co/")
    monkeypatch.setenv("OCU_SUPABASE_ANON_KEY", "learner-anon")
    assert client.get(READ_URL, headers=_bearer(_jwt())).status_code == 200
    assert supabase.call_args.args[0] == "https://learner.supabase.co/auth/v1/user"
    assert supabase.call_args.kwargs["headers"]["apikey"] == "learner-anon"


def test_supabase_down_is_503(client, supabase):
    supabase.side_effect = requests.ConnectionError("down")
    response = client.get(READ_URL, headers=_bearer(_jwt()))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MEMBER_AUTH_UNAVAILABLE"
    supabase.side_effect = None
    supabase.return_value = Mock(status_code=500, ok=False)
    response = client.get(READ_URL, headers=_bearer(_jwt(marker="b")))
    assert response.status_code == 503


def test_stale_owner_cookie_does_not_mask_member_bearer(client, supabase):
    client.cookies.set(OWNER_SESSION_COOKIE, "stale.cookie")
    assert client.get(READ_URL, headers=_bearer(_jwt())).status_code == 200
    assert client.get(READ_URL).status_code == 401


# --- cache --------------------------------------------------------------------------


def test_cache_hit_expiry_and_no_raw_token(client, supabase, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(member_auth.time, "monotonic", lambda: clock[0])
    token = _jwt()
    assert client.get(READ_URL, headers=_bearer(token)).status_code == 200
    assert client.get(READ_URL, headers=_bearer(token)).status_code == 200
    assert supabase.call_count == 1
    stored = json.dumps(list(member_auth._member_cache.items()))
    assert token not in stored
    assert list(member_auth._member_cache) == [member_auth._cache_key(token)]
    clock[0] += 61
    assert client.get(READ_URL, headers=_bearer(token)).status_code == 200
    assert supabase.call_count == 2


def test_cache_never_stores_failures(client, supabase):
    supabase.return_value = Mock(status_code=401, ok=False)
    token = _jwt()
    for _ in range(2):
        assert client.get(READ_URL, headers=_bearer(token)).status_code == 401
    assert supabase.call_count == 2
    assert not member_auth._member_cache


def test_cache_lifetime_capped_by_jwt_exp_and_bounded(supabase, monkeypatch):
    member_auth.verify_member_access_token(_jwt(exp_offset=-5))
    assert not member_auth._member_cache
    monkeypatch.setattr(member_auth, "MEMBER_TOKEN_CACHE_MAX_ENTRIES", 3)
    for index in range(5):
        member_auth.verify_member_access_token(_jwt(marker=str(index)))
    assert len(member_auth._member_cache) == 3


def test_cache_not_used_when_supabase_config_removed(client, supabase, monkeypatch):
    token = _jwt()
    assert client.get(READ_URL, headers=_bearer(token)).status_code == 200
    monkeypatch.delenv("OC_SUPABASE_URL")
    assert client.get(READ_URL, headers=_bearer(token)).status_code == 503


# --- feature switch -----------------------------------------------------------------


def test_feature_switch_off_restores_owner_only(client, owner_token, supabase, monkeypatch):
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    assert client.get(READ_URL, headers=_bearer(_jwt())).status_code == 401
    assert client.get(READ_URL, headers=_bearer(owner_token)).status_code == 200
    assert client.get(READ_URL, headers={"X-API-Key": "test-api-key"}).status_code == 200
    supabase.assert_not_called()


def test_feature_switch_defaults_enabled(monkeypatch):
    assert member_auth.member_reads_enabled() is True
    for value in ("true", "1", "on"):
        monkeypatch.setenv("OC_MEMBER_READS_ENABLED", value)
        assert member_auth.member_reads_enabled() is True
    for value in ("false", "0", "off", "garbage"):
        monkeypatch.setenv("OC_MEMBER_READS_ENABLED", value)
        assert member_auth.member_reads_enabled() is False


# --- route enumeration --------------------------------------------------------------


def _scoped_routes() -> list[tuple[str, str]]:
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith(PREFIXES):
            for method in sorted(route.methods):
                routes.append((method, route.path))
    return routes


def _concrete(path: str) -> str:
    values = {"dimension": "taxonomy"}
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), "1"), path)


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]):
    url = _concrete(path)
    if path == "/api/research/traits":
        url += "?genus=Dracula"
    return client.request(method, url, headers=headers)


def test_route_enumeration_matches_the_declared_member_surface():
    routes = set(_scoped_routes())
    marked = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PREFIXES)
        for method in route.methods
        if getattr(route.endpoint, member_auth.MEMBER_READABLE_ATTR, False)
    }
    assert marked == EXPECTED_MEMBER_READS
    assert EXPECTED_OWNER_ONLY_READS <= routes
    assert all(method == "GET" for method, _ in marked)
    assert any(method != "GET" for method, _ in routes)


def test_every_scoped_route_enforces_member_read_owner_write(client, owner_token, supabase):
    member = _bearer(_jwt())
    owner = _bearer(owner_token)
    failures = []
    for method, path in _scoped_routes():
        member_status = _call(client, method, path, member).status_code
        owner_status = _call(client, method, path, owner).status_code
        anonymous_status = _call(client, method, path, {}).status_code
        member_allowed = (method, path) in EXPECTED_MEMBER_READS
        if member_allowed and member_status in {401, 403}:
            failures.append(("member rejected", method, path, member_status))
        if not member_allowed and member_status not in {401, 403}:
            failures.append(("member admitted", method, path, member_status))
        if owner_status in {401, 403}:
            failures.append(("owner rejected", method, path, owner_status))
        if anonymous_status != 401:
            failures.append(("anonymous admitted", method, path, anonymous_status))
    assert not failures, failures


def test_member_read_matches_owner_read(client, owner_token, supabase):
    """Members receive byte-identical responses to the owner on every opened route."""
    assert client.get(READ_URL, headers=_bearer(_jwt())).json() == TRAITS_PAYLOAD
    for method, path in sorted(EXPECTED_MEMBER_READS):
        owner_response = _call(client, method, path, _bearer(owner_token))
        member_response = _call(client, method, path, _bearer(_jwt()))
        assert owner_response.status_code == member_response.status_code, path
        assert owner_response.content == member_response.content, path


# --- CORS ---------------------------------------------------------------------------


def test_cors_allows_authorization_for_frontend_origin_without_wildcard(client):
    origin = "https://orchidcontinuum.org"
    preflight = client.options(
        READ_URL,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    assert preflight.headers["access-control-allow-credentials"] == "true"
    other = client.options(
        READ_URL,
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert other.headers.get("access-control-allow-origin") not in {"*", "https://evil.example"}


def test_member_marker_never_opens_a_write_method(supabase, owner_token):
    """Defence in depth: even a mistakenly marked write endpoint stays owner-only."""
    from fastapi import APIRouter, Depends, FastAPI

    probe_router = APIRouter(dependencies=[Depends(member_auth.owner_or_member_read)])

    @probe_router.post("/probe")
    @member_auth.member_readable
    def probe_write():
        return {"ok": True}

    @probe_router.get("/probe")
    @member_auth.member_readable
    def probe_read():
        return {"ok": True}

    probe = FastAPI()
    probe.include_router(probe_router)
    probe_client = TestClient(probe)
    assert probe_client.get("/probe", headers=_bearer(_jwt())).status_code == 200
    assert probe_client.post("/probe", headers=_bearer(_jwt())).status_code == 401
    assert probe_client.post("/probe", headers=_bearer(owner_token)).status_code == 200
