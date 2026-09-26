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
from app.candidate_knowledge.models import CandidateKind
from app.evidence_aggregation.models import CANDIDATE_TYPE_MAP
from app.main import app
from app.member_redaction import redact_member_locality
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
    ("GET", "/api/evidence-aggregation/runs/{rid}/items"),
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


OWNER_ACCESS_REQUIRED_BODY = {
    "detail": {"code": "OWNER_ACCESS_REQUIRED", "message": "This view is limited to owner access"}
}


def test_every_scoped_route_enforces_member_read_owner_write(client, owner_token, supabase):
    member = _bearer(_jwt())
    owner = _bearer(owner_token)
    failures = []
    for method, path in _scoped_routes():
        member_response = _call(client, method, path, member)
        owner_status = _call(client, method, path, owner).status_code
        anonymous_status = _call(client, method, path, {}).status_code
        member_allowed = (method, path) in EXPECTED_MEMBER_READS
        if member_allowed and member_response.status_code in {401, 403}:
            failures.append(("member rejected", method, path, member_response.status_code))
        if not member_allowed and (
            member_response.status_code != 403 or member_response.json() != OWNER_ACCESS_REQUIRED_BODY
        ):
            failures.append(("member not given OWNER_ACCESS_REQUIRED", method, path, member_response.status_code))
        if owner_status in {401, 403}:
            failures.append(("owner rejected", method, path, owner_status))
        if anonymous_status != 401:
            failures.append(("anonymous admitted", method, path, anonymous_status))
    # A token Supabase rejects keeps 401 on every route, read or write.
    supabase.return_value = Mock(status_code=401, ok=False)
    invalid = _bearer(_jwt(marker="invalid"))
    for method, path in _scoped_routes():
        status = _call(client, method, path, invalid).status_code
        if status != 401:
            failures.append(("invalid token not 401", method, path, status))
    assert not failures, failures


def test_owner_only_403_is_identical_whether_or_not_the_resource_exists(client, supabase):
    member = _bearer(_jwt())
    urls = [
        ("GET", "/api/candidate-knowledge/candidates/1"),
        ("GET", "/api/candidate-knowledge/candidates/999999999"),
        ("GET", "/api/candidate-knowledge/candidates/not-an-int"),
        ("GET", "/api/candidate-knowledge/runs/424242/items"),
        ("GET", "/api/literature-extraction/papers/does-not-exist"),
        ("GET", "/api/literature-extraction/coverage-audit"),
        ("POST", "/api/candidate-knowledge/preview"),
        ("POST", "/api/evidence-aggregation/aggregates/999999/withdraw"),
        ("PUT", "/api/literature-extraction/papers/x/source-binding"),
    ]
    bodies = set()
    for method, url in urls:
        response = client.request(method, url, headers=member, json={"not": "valid"})
        assert response.status_code == 403, (method, url, response.status_code)
        bodies.add(response.content)
    assert bodies == {json.dumps(OWNER_ACCESS_REQUIRED_BODY, separators=(",", ":")).encode()}


def test_owner_only_route_keeps_401_when_member_cannot_be_verified(client, supabase, monkeypatch):
    url = "/api/candidate-knowledge/candidates/1"
    supabase.side_effect = requests.ConnectionError("down")
    assert client.get(url, headers=_bearer(_jwt())).status_code == 401
    supabase.side_effect = None
    monkeypatch.delenv("OC_SUPABASE_URL")
    assert client.get(url, headers=_bearer(_jwt(marker="b"))).status_code == 401
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    assert client.get(url, headers=_bearer(_jwt(marker="c"))).status_code == 401
    assert client.get(url).json()["detail"] == "Owner session or API key is required"


_NON_REDACTING = ("/api/research/traits", "/api/literature-extraction")


def test_member_read_matches_owner_read(client, owner_token, supabase):
    """Members get the owner's response, except for the locality fields redacted for members."""
    assert client.get(READ_URL, headers=_bearer(_jwt())).json() == TRAITS_PAYLOAD
    for method, path in sorted(EXPECTED_MEMBER_READS):
        owner_response = _call(client, method, path, _bearer(owner_token))
        member_response = _call(client, method, path, _bearer(_jwt()))
        assert owner_response.status_code == member_response.status_code, path
        if path.startswith(_NON_REDACTING) or owner_response.status_code >= 400:
            assert owner_response.content == member_response.content, path
        else:
            assert member_response.json() == redact_member_locality(owner_response.json()), path


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
    assert probe_client.post("/probe", headers=_bearer(_jwt())).status_code == 403
    assert probe_client.post("/probe", headers=_bearer(owner_token)).status_code == 200


# --- locality redaction for members ---------------------------------------------------


# Context plants: every one must reach the owner and never a member.
CONTEXT_PLANTS = (
    "PLANT-GEO-SITE",
    "PLANT-REGION",
    "PLANT-METHOD-TRANSECT",
    "PLANT-TEMPORAL-SITE",
    "PLANT-DATE-PROSE",
    "PLANT-SOURCE-NAME",
    "PLANT-TAXON-LINK",
    "PLANT-QUALIFIER-SITE",
    "PLANT-OCCURS-EXTRACTED",
    "PLANT-ERR-ECHO",
    "PLANT-EA-RATIONALE",
    "PLANT-EA-DEPENDENCE",
    "PLANT-EA-DEP-RATIONALE",
    "PLANT-TOMBSTONE",
    "PLANT-CK-RATIONALE",
)
# Every candidate kind the code knows, plus kinds it does not: occurrence/specimen/
# habitat aliases, lower-case spellings, and unknown kinds (folded into TRAIT_AGGREGATE).
EXTRA_KINDS = (
    "OCCURRENCE",
    "SPECIMEN_REFERENCE",
    "HABITAT",
    "geographic_occurrence",
    "trait",
    " measurement ",
    "Phenology_Event",
    "HABITAT_NOTE",
    "FIELD_NOTE",
)
ALL_AGGREGATION_KINDS = tuple(dict.fromkeys([*CANDIDATE_TYPE_MAP, *CandidateKind, *EXTRA_KINDS]))
ALLOWED = {"MEASUREMENT", "MORPHOLOGY_TERM", "TRAIT", "MOLECULAR_MARKER", "CONSERVATION_ASSERTION", "TAXON"}


def _slug(kind: str) -> str:
    return re.sub(r"[^A-Za-z]", "", str(kind)).upper()


def _prose_plant(kind: str) -> str:
    return f"LOCPROSE{_slug(kind)} near the ridge"


def _clean_plant(kind: str) -> str:
    return f"clean{_slug(kind).lower()}"


def _aggregation_candidate(candidate_id: int, revision: int, **overrides):
    value = {
        "candidate_id": candidate_id,
        "candidate_version": 1,
        "candidate_type": "GEOGRAPHIC_OCCURRENCE",
        "normalized_subject": "Dracula vampira",
        "predicate": f"p{candidate_id}",
        "object_value": "value",
        "source_revision_id": revision,
        "source_anchor_ids": [revision],
        "geographic_context": {"region": "PLANT-REGION", "site": "PLANT-GEO-SITE", "lat": -1.23},
        "method_context": {"protocol": "PLANT-METHOD-TRANSECT"},
        "temporal_context": {"observed_date": "PLANT-DATE-PROSE", "note": "PLANT-TEMPORAL-SITE"},
        "metadata": {"source_name": "PLANT-SOURCE-NAME"},
        "taxon_links": [{"candidate_taxon_id": "t-1", "source_name": "PLANT-TAXON-LINK", "confidence": 0.9}],
    }
    value.update(overrides)
    return value


def _ck_evidence(ident: int, text: str, metadata: dict) -> dict:
    return {
        "source_object_type": "document",
        "source_object_id": ident,
        "revision_id": ident,
        "extraction_run_id": 1,
        "text": text,
        "source_anchors": [{"anchor_id": ident}],
        "metadata": metadata,
    }


@pytest.fixture
def seeded(client, owner_token, monkeypatch):
    from app.candidate_knowledge import routes as ck_routes
    from app.candidate_knowledge.repository import MemoryCandidateRepository
    from app.candidate_knowledge.service import CandidateExtractionService
    from app.evidence_aggregation import routes as ea_routes
    from app.evidence_aggregation.repository import MemoryAggregateRepository
    from app.evidence_aggregation.service import EvidenceAggregationService

    ck_repo = MemoryCandidateRepository()
    monkeypatch.setattr(ck_routes, "REPOSITORY", ck_repo)
    monkeypatch.setattr(ck_routes, "SERVICE", CandidateExtractionService(ck_repo))
    ea_repo = MemoryAggregateRepository()
    monkeypatch.setattr(ea_routes, "REPOSITORY", ea_repo)
    monkeypatch.setattr(ea_routes, "SERVICE", EvidenceAggregationService(ea_repo))
    owner = _bearer(owner_token)

    # Evidence aggregation: one prose and one clean value per kind, each its own cluster.
    candidates, expected_kept, expected_redacted = [], set(), set()
    next_id = 1
    for kind in ALL_AGGREGATION_KINDS:
        for value in (_prose_plant(kind), _clean_plant(kind)):
            candidates.append(_aggregation_candidate(next_id, 100 + next_id, candidate_type=kind, object_value=value))
            next_id += 1
            if value == _clean_plant(kind) and str(kind).strip().upper() in ALLOWED:
                expected_kept.add(value.lower())
            else:
                expected_redacted.add(value.lower())
    numeric = _aggregation_candidate(
        next_id, 100 + next_id, candidate_type="MEASUREMENT", object_value=None, numeric_value=4.0, unit="mm"
    )
    withdraw_target = _aggregation_candidate(next_id + 1, 101 + next_id, candidate_type="TRAIT", object_value="target")
    candidates += [numeric, withdraw_target]
    run = client.post("/api/evidence-aggregation/preview", headers=owner, json={"candidates": candidates})
    assert run.status_code == 201, run.text
    rid = run.json()["aggregate_run_id"]
    assert client.post(f"/api/evidence-aggregation/runs/{rid}/execute", headers=owner).status_code == 200
    aggregates = client.get("/api/evidence-aggregation/aggregates?limit=200", headers=owner).json()["items"]
    assert len(aggregates) == len(candidates)

    dependence = client.post(
        "/api/evidence-aggregation/sources/dependence",
        headers=owner,
        json={"candidate_ids": [1, 2], "dependence": "PLANT-EA-DEPENDENCE", "rationale": "PLANT-EA-DEP-RATIONALE"},
    )
    assert dependence.status_code == 200, dependence.text
    review = client.get("/api/evidence-aggregation/reviews", headers=owner).json()["items"][0]
    resolved = client.post(
        f"/api/evidence-aggregation/reviews/{review['review_id']}/resolve",
        headers=owner,
        json={"action": "DEFER", "rationale": "PLANT-EA-RATIONALE"},
    )
    assert resolved.status_code == 200, resolved.text
    withdrawn = client.post(
        f"/api/evidence-aggregation/aggregates/{next(x for x in aggregates if x['normalized_object'] == 'target')['aggregate_id']}/withdraw",
        headers=owner,
        json={"reason": "PLANT-TOMBSTONE"},
    )
    assert withdrawn.status_code == 200, withdrawn.text

    # Candidate knowledge: declared facts for every CandidateKind (prose + clean value),
    # a regex-extracted "occurs in" locality, qualifiers, and an EXTRACTION_FAILURE whose
    # message echoes caller text.
    ck_facts, ck_kept, ck_redacted = [], set(), set()
    for kind in CandidateKind:
        for value in (_prose_plant(kind), _clean_plant(kind)):
            ck_facts.append(
                {
                    "kind": kind.value,
                    "subject": "Dracula vampira",
                    "predicate": f"p-{kind.value}-{len(ck_facts)}",
                    "object_value": value,
                    "qualifiers": {"site": "PLANT-QUALIFIER-SITE"},
                }
            )
            (ck_kept if value == _clean_plant(kind) and kind.value in ALLOWED else ck_redacted).add(value)
    ck_run = client.post(
        "/api/candidate-knowledge/preview",
        headers=owner,
        json={
            "evidence": [
                _ck_evidence(1, "Dracula vampira occurs in PLANT-OCCURS-EXTRACTED valley.", {"subject": "Dracula vampira"}),
                _ck_evidence(2, "declared", {"candidate_facts": ck_facts}),
                _ck_evidence(
                    3,
                    "failing",
                    {"candidate_facts": [{"kind": "PLANT-ERR-ECHO near ridge", "subject": "x", "predicate": "y"}]},
                ),
            ]
        },
    )
    assert ck_run.status_code == 201, ck_run.text
    ck_rid = ck_run.json()["candidate_run_id"]
    assert client.post(f"/api/candidate-knowledge/runs/{ck_rid}/execute", headers=owner).status_code == 200
    ck_review = next(
        x
        for x in client.get("/api/candidate-knowledge/reviews", headers=owner).json()["items"]
        if x["category"] == "CANDIDATE_REQUIRES_HUMAN_REVIEW"
    )
    ck_resolved = client.post(
        f"/api/candidate-knowledge/reviews/{ck_review['review_id']}/resolve",
        headers=owner,
        json={"decision": "REQUEST_CHANGES", "rationale": "PLANT-CK-RATIONALE"},
    )
    return {
        "rid": rid,
        "aid": aggregates[0]["aggregate_id"],
        "numeric_aid": next(x for x in aggregates if x["measurement_summary"]["measurements"])["aggregate_id"],
        "cid": aggregates[0]["cluster_id"],
        "ck_rid": ck_rid,
        "ea_kept": expected_kept,
        "ea_redacted": expected_redacted,
        "ck_kept": ck_kept,
        "ck_redacted": ck_redacted,
        "ck_resolved": ck_resolved.status_code,
    }


def _seeded_urls(seeded) -> list[str]:
    values = {"rid": seeded["rid"], "aid": seeded["aid"], "cid": seeded["cid"], "run_id": seeded["ck_rid"]}
    urls = []
    for method, path in sorted(EXPECTED_MEMBER_READS):
        if not path.startswith(("/api/evidence-aggregation", "/api/candidate-knowledge")):
            continue
        if path.endswith("/{dimension}"):
            for dimension in ("taxonomy", "temporal", "geographic", "measurements"):
                urls.append(path.replace("{aid}", str(seeded["aid"])).replace("{dimension}", dimension))
            continue
        urls.append(re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]), path))
    numeric_aid = seeded["numeric_aid"]
    urls += [
        f"/api/evidence-aggregation/aggregates/{numeric_aid}",
        f"/api/evidence-aggregation/aggregates/{numeric_aid}/measurements",
        "/api/evidence-aggregation/reviews?state=RESOLVED",
        "/api/evidence-aggregation/reviews?limit=200",
        "/api/evidence-aggregation/aggregates?limit=200",
        "/api/evidence-aggregation/aggregates?status=SUPERSEDED",
        "/api/candidate-knowledge/candidates?limit=200",
        "/api/candidate-knowledge/reviews?state=RESOLVED",
        "/api/candidate-knowledge/reviews?limit=200",
        "/api/candidate-knowledge/conflicts",
    ]
    return urls


def _collect(client, urls, headers) -> str:
    text = ""
    for url in urls:
        response = client.get(url, headers=headers)
        assert response.status_code == 200, (url, response.text)
        text += response.text
    return text


def test_planted_locality_never_reaches_a_member(client, owner_token, supabase, seeded):
    assert seeded["ck_resolved"] == 200
    urls = _seeded_urls(seeded)
    for url in urls:
        owner_response = client.get(url, headers=_bearer(owner_token))
        member_response = client.get(url, headers=_bearer(_jwt()))
        assert owner_response.status_code == member_response.status_code == 200, (url, owner_response.text)
        assert member_response.json() == redact_member_locality(owner_response.json()), url
    owner_text = _collect(client, urls, _bearer(owner_token)).lower()
    member_text = _collect(client, urls, _bearer(_jwt())).lower()
    plants = [p.lower() for p in CONTEXT_PLANTS] + sorted(seeded["ea_redacted"]) + [p.lower() for p in seeded["ck_redacted"]]
    missing_for_owner = [p for p in plants if p not in owner_text]
    assert not missing_for_owner, missing_for_owner
    leaked = [p for p in plants if p in member_text]
    assert not leaked, leaked


def test_allowlisted_clean_values_still_reach_members(client, supabase, seeded):
    member_text = _collect(client, _seeded_urls(seeded), _bearer(_jwt())).lower()
    assert seeded["ea_kept"] and seeded["ck_kept"]
    missing = [v for v in sorted(seeded["ea_kept"]) + sorted(v.lower() for v in seeded["ck_kept"]) if v not in member_text]
    assert not missing, missing


@pytest.mark.parametrize("kind", ALL_AGGREGATION_KINDS)
def test_every_kind_is_allowlisted_or_redacted_on_each_aggregate_view(client, supabase, seeded, owner_token, kind):
    member = _bearer(_jwt())
    owner_items = client.get("/api/evidence-aggregation/aggregates?limit=200", headers=_bearer(owner_token)).json()["items"]
    prose = next(x for x in owner_items if x["normalized_object"] == _prose_plant(kind).lower())
    clean = next(x for x in owner_items if x["normalized_object"] == _clean_plant(kind).lower())
    keep_clean = str(kind).strip().upper() in ALLOWED
    for record in (prose, clean):
        aid = record["aggregate_id"]
        views = [
            client.get(f"/api/evidence-aggregation/aggregates/{aid}", headers=member).json(),
            *client.get(f"/api/evidence-aggregation/aggregates/{aid}/versions", headers=member).json()["items"],
            next(
                x
                for x in client.get("/api/evidence-aggregation/aggregates?limit=200", headers=member).json()["items"]
                if x["aggregate_id"] == aid
            ),
            next(
                x
                for x in client.get("/api/evidence-aggregation/export", headers=member).json()["items"]
                if x["aggregate_id"] == aid
            ),
        ]
        for view in views:
            if record is clean and keep_clean:
                assert view["normalized_object"] == record["normalized_object"], (kind, view)
                assert "normalized_object_redacted" not in view
            else:
                assert view["normalized_object"] is None and view["normalized_object_redacted"] is True, (kind, view)


@pytest.mark.parametrize("kind", list(CandidateKind))
def test_every_candidate_kind_is_allowlisted_or_redacted(client, supabase, seeded, kind):
    items = client.get("/api/candidate-knowledge/candidates?limit=200", headers=_bearer(_jwt())).json()["items"]
    mine = [x for x in items if x["kind"] == kind.value and x["predicate"].startswith(f"p-{kind.value}-")]
    assert len(mine) == 2
    for item in mine:
        if kind.value in ALLOWED and item["object_value"] is not None:
            assert item["object_value"] == _clean_plant(kind)
        else:
            assert item["object_value"] is None and item["object_value_redacted"] is True
        assert item["qualifiers"] is None and item["qualifiers_redacted"] is True


def test_reviewer_notes_and_error_echoes_are_redacted(client, supabase, seeded):
    member = _bearer(_jwt())
    ea_reviews = client.get("/api/evidence-aggregation/reviews?limit=200", headers=member).json()["items"]
    dependence = next(x for x in ea_reviews if x["category"] == "SOURCE_INDEPENDENCE_DECISION")
    assert dependence["evidence"]["rationale"] is None and dependence["evidence"]["rationale_redacted"] is True
    assert dependence["evidence"]["dependence"] is None and dependence["evidence"]["dependence_redacted"] is True
    resolved = client.get("/api/evidence-aggregation/reviews?state=RESOLVED", headers=member).json()["items"]
    assert resolved and all(x["rationale"] is None and x["rationale_redacted"] for x in resolved)
    tombstones = client.get("/api/evidence-aggregation/tombstones", headers=member).json()["items"]
    assert tombstones and all(x["reason"] is None and x["reason_redacted"] for x in tombstones)
    ck_reviews = client.get("/api/candidate-knowledge/reviews?limit=200", headers=member).json()["items"]
    failure = next(x for x in ck_reviews if x["category"] == "EXTRACTION_FAILURE")
    assert failure["evidence"]["message"] is None and failure["evidence"]["message_redacted"] is True
    assert failure["evidence"]["code"] == "ValueError"
    ck_resolved = client.get("/api/candidate-knowledge/reviews?state=RESOLVED", headers=member).json()["items"]
    assert ck_resolved and all(x["rationale"] is None and x["rationale_redacted"] for x in ck_resolved)
    aggregate = client.get(f"/api/evidence-aggregation/aggregates/{seeded['aid']}", headers=member).json()
    assert aggregate["taxonomic_context"]["source_names"] is None
    assert aggregate["taxonomic_context"]["source_names_redacted"] is True
    assert aggregate["geographic_context"]["geographic_context_redacted"] is True


def test_value_shape_and_marker_screen():
    from app.member_redaction import _value_shape_ok

    for ok in ("4.5 mm", "3-5 cm", "saccate", "hairy sepals", "matK", 12, 4.25, "4:length:base", "MULTIPLE_VALUES"):
        assert _value_shape_ok(ok), ok
    for bad in (
        "March near LOC-PHEN-RIDGE",
        "1200 m",
        "12 30 N",
        "-12.3456",
        "5 km N of town",
        "found at the ridge trail",
        "collected on slope",
        "x" * 41,
        "one two three four five",
        True,
        None,
        {"a": 1},
    ):
        assert not _value_shape_ok(bad), bad


def test_owner_and_api_key_responses_are_the_unmodified_handler_output(client, owner_token, supabase, seeded):
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    from app.candidate_knowledge import routes as ck_routes
    from app.evidence_aggregation import routes as ea_routes

    direct = {
        "/api/evidence-aggregation/aggregates": ea_routes.aggregates(
            aggregate_type=None, status=None, review_state=None, conflict_state=None,
            minimum_confidence=None, limit=50, offset=0,
        ),
        f"/api/evidence-aggregation/aggregates/{seeded['aid']}": ea_routes.aggregate(seeded["aid"]),
        f"/api/evidence-aggregation/runs/{seeded['rid']}/items": ea_routes.items(seeded["rid"], limit=100, offset=0),
        "/api/candidate-knowledge/candidates": ck_routes.candidates(
            kind=None, review_state=None, active=True, limit=50, offset=0
        ),
    }
    for url, payload in direct.items():
        expected = JSONResponse(jsonable_encoder(payload)).body
        assert client.get(url, headers=_bearer(owner_token)).content == expected, url
        assert client.get(url, headers={"X-API-Key": "test-api-key"}).content == expected, url


def test_redaction_does_not_trust_a_caller_context_that_mimics_the_summary_shape():
    mimic = {"geographic_context": {"contexts": [], "scopes": [], "universalized": "PLANT", "site": "PLANT"}}
    assert "PLANT" not in json.dumps(redact_member_locality(mimic))
    exact_mimic = {"contexts": ["PLANT"], "scopes": ["PLANT"], "universalized": "PLANT"}
    assert "PLANT" not in json.dumps(redact_member_locality(exact_mimic))
    temporal = {"contexts": [], "earliest_evidence_date": "PLANT near", "latest_evidence_date": "2024-05-01",
                "superseded_candidate_ids": [], "trend_conclusion": None}
    redacted = redact_member_locality(temporal)
    assert redacted["earliest_evidence_date"] is None and redacted["latest_evidence_date"] == "2024-05-01"


def test_value_redaction_fails_closed_on_missing_or_conflicting_type_fields():
    assert redact_member_locality({"object_value": "clean"})["object_value_redacted"] is True
    folded = {"aggregate_type": "TRAIT_AGGREGATE", "candidate_type": "habitat_note", "normalized_object": "clean"}
    assert redact_member_locality(folded)["normalized_object_redacted"] is True
    habitat = {"aggregate_type": "HABITAT_AGGREGATE", "normalized_object": "clean"}
    assert redact_member_locality(habitat)["normalized_object_redacted"] is True
    kept = redact_member_locality({"kind": " trait ", "object_value": "hairy sepals", "unit": "mm"})
    assert kept == {"kind": " trait ", "object_value": "hairy sepals", "unit": "mm"}
    unit = redact_member_locality({"kind": "MEASUREMENT", "object_value": "4", "unit": "m above the ridge"})
    assert unit["unit"] is None and unit["unit_redacted"] is True
