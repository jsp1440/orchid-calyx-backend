"""Member feedback submission (owner decision "Members submit, owner reviews").

Drives the real ``app.main`` application with real owner-session, API-key and
member authentication; only the Supabase HTTP call is mocked, so these tests
never reach the network. Store-dependent tests run against the file store and
the PostgreSQL store (``tests/evidence_feedback_stores.py``).
"""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app import member_auth, rate_limit
from app.evidence_feedback import routes
from app.main import app
from app.security import create_owner_session_token
from tests.evidence_feedback_stores import STORES, make_store

TEST_API_KEY = "local-test-api-key-not-a-credential"
TEST_SESSION_SECRET = "local-test-session-secret-not-a-credential"
BASE = "/api/evidence-feedback"
REVIEW = f"{BASE}/review/cases"
MEMBER_A_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MEMBER_B_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OWNER_ACCESS_REQUIRED_BODY = {
    "detail": {
        "code": "OWNER_ACCESS_REQUIRED",
        "message": "This view is limited to owner access",
    }
}
FEEDBACK_DISABLED_BODY = {"detail": dict(member_auth.MEMBER_FEEDBACK_DISABLED)}
RECEIPT_FIELDS = {"created", "case_id", "status"}
OBJECT_RECEIPT_FIELDS = {"object_id", "object_type", "version_hash"}
DISPLAYED = {"term": "labellum", "definition": "a modified petel"}


def _jwt(marker: str) -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"sub": marker, "exp": int(time.time() + 3600), "m": marker}
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.sig"


TOKEN_A = _jwt("member-a")
TOKEN_B = _jwt("member-b")
TOKEN_REJECTED = _jwt("rejected")
MEMBER_IDS = {TOKEN_A: MEMBER_A_UUID, TOKEN_B: MEMBER_B_UUID}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def owner_headers() -> dict[str, str]:
    return bearer(str(create_owner_session_token("owner")["token"]))


MEMBER_A = bearer(TOKEN_A)
MEMBER_B = bearer(TOKEN_B)
API_KEY = {"X-API-Key": TEST_API_KEY}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.delenv("OC_MEMBER_READS_ENABLED", raising=False)
    monkeypatch.setenv(member_auth.MEMBER_FEEDBACK_ENV, "true")
    monkeypatch.delenv(rate_limit.MEMBER_WRITE_RATE_LIMIT_ENV, raising=False)
    monkeypatch.delenv(rate_limit.MEMBER_WRITE_RATE_WINDOW_ENV, raising=False)
    member_auth.clear_member_token_cache()
    rate_limit.MEMBER_WRITE_LIMITER.reset()
    yield
    member_auth.clear_member_token_cache()
    rate_limit.MEMBER_WRITE_LIMITER.reset()


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    """Supabase ``/auth/v1/user``: known member tokens verify, anything else is 401."""

    def verify(url, headers, timeout):
        token = headers["Authorization"].removeprefix("Bearer ")
        user_id = MEMBER_IDS.get(token)
        if user_id is None:
            return Mock(status_code=401, ok=False)
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {"id": user_id, "email": f"{user_id}@example.org"}
        return response

    mock = Mock(side_effect=verify)
    monkeypatch.setattr("app.university.learner_auth.requests.get", mock)
    return mock


@pytest.fixture(params=STORES)
def store(request, tmp_path, monkeypatch):
    return make_store(request.param, tmp_path, monkeypatch)


@pytest.fixture
def file_store(tmp_path, monkeypatch):
    return make_store("file", tmp_path, monkeypatch)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def register(
    client: TestClient, headers: dict[str, str], payload: dict | None = None, **extra
):
    return client.post(
        f"{BASE}/objects",
        json={
            "object_id": "lexicon:labellum",
            "object_type": "lexicon",
            "payload": payload or DISPLAYED,
            **extra,
        },
        headers=headers,
    )


def case_body(
    version_hash: str, statement: str = "Petal is misspelled.", **overrides
) -> dict:
    return {
        "object_id": "lexicon:labellum",
        "object_version_hash": version_hash,
        "object_type": "lexicon",
        "page_context": "/lexicon/labellum",
        "feedback_class": "suggest_correction",
        "statement": statement,
        "proposed_replacement": "a modified petal",
        "citation": None,
        "source_partner_id": None,
        "defect_kind": "typo",
        "severity": "normal",
        **overrides,
    }


def submit(
    client: TestClient,
    headers: dict[str, str],
    statement: str = "Petal is misspelled.",
    **overrides,
):
    registered = register(client, headers)
    assert registered.status_code == 201, registered.text
    return client.post(
        f"{BASE}/cases",
        json=case_body(registered.json()["version_hash"], statement, **overrides),
        headers=headers,
    )


def member_actor(uuid: str) -> str:
    """The stable actor the Supabase verifier derives for ``uuid``."""
    from app.university.learner_auth import _stable_actor

    return _stable_actor(uuid, invalid_identity_code="X", audience="Member")


# --- submission --------------------------------------------------------------------


def test_member_submit_returns_201_and_a_receipt_only(store, client, supabase):
    registered = register(client, MEMBER_A)
    assert registered.status_code == 201, registered.text
    assert set(registered.json()) == OBJECT_RECEIPT_FIELDS

    response = client.post(
        f"{BASE}/cases",
        json=case_body(registered.json()["version_hash"]),
        headers=MEMBER_A,
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == RECEIPT_FIELDS
    assert receipt["created"] is True
    assert receipt["case_id"].startswith("efc-")
    assert receipt["status"] == "pending_review"
    for private in (
        MEMBER_A_UUID,
        member_actor(MEMBER_A_UUID),
        "submitter",
        "reviewer",
        "member:",
    ):
        assert private not in response.text

    stored = store.repository().get_case(receipt["case_id"])
    assert stored.submitter_id == f"member:{member_actor(MEMBER_A_UUID)}"
    assert stored.status.value == "pending_review"


def test_member_resubmitting_their_own_text_gets_their_own_case_back(
    store, client, supabase
):
    first = submit(client, MEMBER_A).json()
    again = submit(client, MEMBER_A).json()
    assert again == {
        "created": False,
        "case_id": first["case_id"],
        "status": "pending_review",
    }


def test_duplicate_from_member_b_leaks_none_of_member_a(store, client, supabase):
    a_statement = "Petal is  MISSPELLED here."
    a_page = "/lexicon/labellum?from=member-a-private-context"
    a = submit(
        client,
        MEMBER_A,
        a_statement,
        page_context=a_page,
        citation="A private citation",
    )
    assert a.status_code == 201
    a_case = a.json()["case_id"]

    # Same fingerprint (whitespace/case-normalised text, same citation), different page.
    b = submit(
        client, MEMBER_B, "petal is misspelled here.", citation="A private citation"
    )
    assert b.status_code == 201, b.text
    assert b.json() == {
        "created": False,
        "case_id": None,
        "status": routes.MEMBER_DUPLICATE_STATUS,
    }
    for leaked in (
        a_case,
        a_statement,
        a_page,
        "member-a-private-context",
        MEMBER_A_UUID,
        member_actor(MEMBER_A_UUID),
        "efc-",
    ):
        assert leaked not in b.text, leaked

    # B's registration of the snapshot A registered first says nothing about A.
    b_object = register(client, MEMBER_B)
    assert set(b_object.json()) == OBJECT_RECEIPT_FIELDS

    # The duplicate is recorded for the owner, attributed to B, and A's case is intact.
    repository = store.repository()
    assert (
        repository.get_case(a_case).submitter_id
        == f"member:{member_actor(MEMBER_A_UUID)}"
    )
    duplicates = [
        e
        for e in repository.list_events(a_case)
        if e["event"] == "duplicate_submission_suppressed"
    ]
    assert [e["actor_id"] for e in duplicates] == [
        f"member:{member_actor(MEMBER_B_UUID)}"
    ]


def test_member_duplicate_of_an_owner_case_gets_no_case_id(store, client, supabase):
    owner_case = submit(client, owner_headers()).json()["case"]["case_id"]
    response = submit(client, MEMBER_A)
    assert response.json() == {
        "created": False,
        "case_id": None,
        "status": routes.MEMBER_DUPLICATE_STATUS,
    }
    assert owner_case not in response.text
    assert '"owner"' not in response.text


def test_member_b_cannot_read_member_a_case_and_cannot_tell_it_exists(
    store, client, supabase
):
    a_case = submit(client, MEMBER_A).json()["case_id"]
    owner_case = submit(client, owner_headers(), "Owner-only report.").json()["case"][
        "case_id"
    ]

    own = client.get(f"{BASE}/cases/{a_case}", headers=MEMBER_A)
    assert own.status_code == 200
    assert set(own.json()) == {
        "case_id",
        "status",
        "disposition",
        "resolution",
        "resulting_version_hash",
    }
    assert own.json()["case_id"] == a_case

    responses = [
        client.get(f"{BASE}/cases/{case_id}", headers=MEMBER_B)
        for case_id in (a_case, owner_case, "efc-000000000000000000000000")
    ]
    assert {r.status_code for r in responses} == {404}
    assert {r.content for r in responses} == {b'{"detail":{"code":"CASE_NOT_FOUND"}}'}
    # A member cannot read the owner's case either.
    assert client.get(f"{BASE}/cases/{owner_case}", headers=MEMBER_A).status_code == 404


# --- owner-only surfaces -----------------------------------------------------------


def _owner_only_calls(case_id: str) -> list[tuple[str, str, dict | None]]:
    return [
        (
            "POST",
            f"{BASE}/cases/{case_id}/accept-trivial",
            {"corrected_payload": {"d": "x"}},
        ),
        ("GET", REVIEW, None),
        ("GET", f"{REVIEW}/{case_id}", None),
        ("POST", f"{REVIEW}/{case_id}/decision", {"decision": "reject", "reason": "r"}),
        (
            "POST",
            f"{REVIEW}/{case_id}/decision",
            {"decision": "accept_trivial", "corrected_payload": {"d": "x"}},
        ),
    ]


def test_member_gets_403_on_accept_trivial_and_every_review_route(
    store, client, supabase
):
    case_id = submit(client, MEMBER_A).json()["case_id"]
    bodies = set()
    for case in (case_id, "efc-missing"):
        for method, url, body in _owner_only_calls(case):
            response = client.request(method, url, json=body, headers=MEMBER_A)
            assert response.status_code == 403, (method, url, response.text)
            assert response.json() == OWNER_ACCESS_REQUIRED_BODY, (method, url)
            bodies.add(response.content)
    assert len(bodies) == 1  # identical whether or not the case exists
    stored = store.repository().get_case(case_id)
    assert stored.status.value == "pending_review"
    assert stored.reviewer_id is None


def test_accept_trivial_keeps_its_owner_and_api_key_behaviour(
    file_store, client, supabase
):
    # The owner registered the displayed record, so the member's case takes the
    # trusted (registered) lexicon type and the deterministic path stays open.
    assert register(client, owner_headers()).status_code == 201
    case_id = submit(client, MEMBER_A).json()["case_id"]
    stored = file_store.repository().get_case(case_id)
    assert stored.object_type_source == "registered"
    assert stored.disposition.value == "auto_correctable"
    anonymous = client.post(
        f"{BASE}/cases/{case_id}/accept-trivial", json={"corrected_payload": {"d": "x"}}
    )
    assert anonymous.status_code == 401
    accepted = client.post(
        f"{BASE}/cases/{case_id}/accept-trivial",
        json={
            "corrected_payload": {"term": "labellum", "definition": "a modified petal"}
        },
        headers=owner_headers(),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "resolved"
    # The member now sees their own case resolved, and nothing about the reviewer.
    status = client.get(f"{BASE}/cases/{case_id}", headers=MEMBER_A)
    assert status.status_code == 200
    assert status.json()["status"] == "resolved"
    assert "owner" not in status.text


def test_owner_review_shows_who_registered_the_snapshot(store, client, supabase):
    case_id = submit(client, MEMBER_A).json()["case_id"]
    detail = client.get(f"{REVIEW}/{case_id}", headers=owner_headers())
    assert detail.status_code == 200, detail.text
    assert detail.json()["object_version"]["registered_by_role"] == "member"
    # Raw member identity never reaches the owner review either: opaque refs only.
    assert MEMBER_A_UUID not in detail.text
    assert member_actor(MEMBER_A_UUID) not in detail.text

    assert detail.json()["object_version_provisional"] is True
    assert detail.json()["case"]["submitter_role"] == "member"

    # The owner registering the same content creates the canonical version,
    # which supersedes the member's provisional snapshot in the review.
    again = register(client, owner_headers())
    assert again.status_code == 201
    assert again.json()["registered_by_role"] == "owner_session"
    superseded = client.get(f"{REVIEW}/{case_id}", headers=owner_headers()).json()
    assert superseded["object_version"]["registered_by_role"] == "owner_session"
    assert superseded["object_version_provisional"] is False
    fresh = register(client, owner_headers(), payload={"term": "column"})
    assert fresh.json()["registered_by_role"] == "owner_session"
    by_key = register(client, API_KEY, payload={"term": "sepal"})
    assert by_key.json()["registered_by_role"] == "api_key"


def test_member_cannot_claim_version_lineage_or_store_an_oversized_snapshot(
    file_store, client, supabase
):
    base = register(client, owner_headers()).json()["version_hash"]
    lineage = register(
        client,
        MEMBER_A,
        payload={"term": "labellum", "definition": "x"},
        previous_version_hash=base,
    )
    assert lineage.status_code == 422
    assert lineage.json()["detail"] == {"code": "MEMBER_LINEAGE_CLAIM_NOT_ACCEPTED"}

    huge = {"definition": "x" * (routes.MEMBER_OBJECT_PAYLOAD_MAX_BYTES + 1)}
    too_large = register(client, MEMBER_A, payload=huge)
    assert too_large.status_code == 413
    assert too_large.json()["detail"] == {"code": "OBJECT_PAYLOAD_TOO_LARGE"}
    assert len(file_store.repository().list_object_versions("lexicon:labellum")) == 1

    # The owner keeps both abilities.
    owner_lineage = register(
        client,
        owner_headers(),
        payload={"term": "labellum", "definition": "y"},
        previous_version_hash=base,
    )
    assert owner_lineage.status_code == 201


# --- rate limiting -----------------------------------------------------------------


def test_member_writes_are_rate_limited_per_subject_not_per_address(
    file_store, client, supabase, monkeypatch
):
    monkeypatch.setenv(rate_limit.MEMBER_WRITE_RATE_LIMIT_ENV, "2")
    assert register(client, owner_headers()).status_code == 201
    version = register(client, MEMBER_A).json()["version_hash"]
    for index in range(2):
        ok = client.post(
            f"{BASE}/cases",
            json=case_body(version, f"Report {index}."),
            headers={**MEMBER_A, "X-Forwarded-For": f"198.51.100.{index}"},
        )
        assert ok.status_code == 201, ok.text
    # A new address does not buy a new allowance.
    limited = client.post(
        f"{BASE}/cases",
        json=case_body(version, "Report 3."),
        headers={**MEMBER_A, "X-Forwarded-For": "203.0.113.9"},
    )
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "MEMBER_RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    assert (
        len(
            file_store.repository().list_cases(
                status=None, object_type=None, limit=10, before=None
            )
        )
        == 2
    )

    # Another member from the same address keeps their own allowance; the owner is never limited.
    b = client.post(
        f"{BASE}/cases", json=case_body(version, "Report by B."), headers=MEMBER_B
    )
    assert b.status_code == 201
    for index in range(3):
        owner = client.post(
            f"{BASE}/cases",
            json=case_body(version, f"Owner {index}."),
            headers=owner_headers(),
        )
        assert owner.status_code == 201

    # The limiter holds no member identifier, only keyed digests.
    keys = " ".join(rate_limit.MEMBER_WRITE_LIMITER._events)
    for identity in (
        MEMBER_A_UUID,
        MEMBER_B_UUID,
        member_actor(MEMBER_A_UUID),
        member_actor(MEMBER_B_UUID),
    ):
        assert identity not in keys


def test_object_registration_is_rate_limited_too(
    file_store, client, supabase, monkeypatch
):
    monkeypatch.setenv(rate_limit.MEMBER_WRITE_RATE_LIMIT_ENV, "1")
    assert register(client, MEMBER_A).status_code == 201
    assert register(client, MEMBER_A).status_code == 429


def test_subject_key_is_keyed_and_not_a_plain_hash():
    import hashlib

    key = rate_limit.subject_key("member:abc")
    assert key == rate_limit.subject_key("member:abc")
    assert key != rate_limit.subject_key("member:abd")
    assert key != hashlib.sha256(b"member:abc").hexdigest()


# --- switches and anonymous callers ------------------------------------------------


def _member_calls(version_hash: str) -> list[tuple[str, str, dict | None]]:
    return [
        (
            "POST",
            f"{BASE}/objects",
            {
                "object_id": "lexicon:labellum",
                "object_type": "lexicon",
                "payload": DISPLAYED,
            },
        ),
        ("POST", f"{BASE}/cases", case_body(version_hash)),
        ("GET", f"{BASE}/cases/efc-anything", None),
    ]


@pytest.mark.parametrize("value", [None, "", "false", "0", "off", "enabled"])
def test_kill_switch_off_or_unset_returns_403_and_writes_nothing(
    file_store, client, supabase, monkeypatch, value
):
    version = register(client, owner_headers()).json()["version_hash"]
    if value is None:
        monkeypatch.delenv(member_auth.MEMBER_FEEDBACK_ENV, raising=False)
    else:
        monkeypatch.setenv(member_auth.MEMBER_FEEDBACK_ENV, value)
    assert member_auth.member_feedback_enabled() is False
    written = file_store.files_written()
    for method, url, body in _member_calls(version):
        response = client.request(method, url, json=body, headers=MEMBER_A)
        assert response.status_code == 403, (method, url)
        assert response.json() == FEEDBACK_DISABLED_BODY
    assert file_store.files_written() == written
    # The owner flow does not depend on the member switch.
    assert submit(client, owner_headers()).status_code == 201


def test_member_reads_off_returns_403_even_with_feedback_on(
    file_store, client, supabase, monkeypatch
):
    version = register(client, owner_headers()).json()["version_hash"]
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    for method, url, body in _member_calls(version):
        response = client.request(method, url, json=body, headers=MEMBER_A)
        assert response.status_code == 403, (method, url)
        assert response.json() == FEEDBACK_DISABLED_BODY
    # Owner-only routes keep their reads-off behaviour (401, as before this change).
    assert client.get(REVIEW, headers=MEMBER_A).status_code == 401
    assert (
        client.post(
            f"{BASE}/cases/efc-x/accept-trivial",
            json={"corrected_payload": {}},
            headers=MEMBER_A,
        ).status_code
        == 401
    )


def test_anonymous_invalid_and_forged_callers_get_401(file_store, client, supabase):
    version = register(client, owner_headers()).json()["version_hash"]
    forged_owner = bearer("abc." + "0" * 64)
    for headers in (
        {},
        bearer(TOKEN_REJECTED),
        forged_owner,
        {"X-API-Key": "wrong"},
        {**MEMBER_A, "X-API-Key": "wrong"},
    ):
        for method, url, body in _member_calls(version):
            response = client.request(method, url, json=body, headers=headers)
            assert response.status_code == 401, (headers, method, url, response.text)
    forwarded = [
        call.kwargs["headers"]["Authorization"] for call in supabase.call_args_list
    ]
    assert f"Bearer {forged_owner['Authorization'].split()[1]}" not in forwarded


def test_supabase_unavailable_keeps_401_for_members(file_store, client, supabase):
    supabase.side_effect = None
    supabase.return_value = Mock(status_code=500, ok=False)
    response = register(client, MEMBER_A)
    assert response.status_code == 401


# --- owner flow unchanged ----------------------------------------------------------

CASE_FIELDS = {
    "case_id",
    "fingerprint",
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
    "submitter_id",
    "source_partner_id",
    "defect_kind",
    "severity",
    "related_case_ids",
    "resolution",
    "resulting_version_hash",
    "reviewer_id",
    "submitter_role",
    "object_type_source",
}


@pytest.mark.parametrize(
    "headers", [owner_headers, lambda: API_KEY], ids=["owner", "api_key"]
)
def test_owner_and_api_key_flow_is_unchanged(store, client, supabase, headers):
    registered = register(client, headers())
    assert registered.status_code == 201
    assert {
        "object_id",
        "object_type",
        "version_hash",
        "payload",
        "created_at",
        "previous_version_hash",
    } <= set(registered.json())
    first = client.post(
        f"{BASE}/cases",
        json=case_body(registered.json()["version_hash"]),
        headers=headers(),
    )
    assert first.status_code == 201
    body = first.json()
    assert set(body) == {"created", "duplicate_of", "case"}
    assert body["created"] is True and body["duplicate_of"] is None
    assert set(body["case"]) == CASE_FIELDS
    repeat = client.post(
        f"{BASE}/cases",
        json=case_body(registered.json()["version_hash"]),
        headers=headers(),
    )
    assert repeat.json()["created"] is False
    assert repeat.json()["duplicate_of"] == body["case"]["case_id"]
    status = client.get(f"{BASE}/cases/{body['case']['case_id']}", headers=headers())
    assert status.status_code == 200
    # Owner and API-key calls never consult Supabase.
    assert supabase.call_count == 0


def test_owner_sees_a_member_owned_case_as_not_visible_on_the_submitter_route(
    file_store, client, supabase
):
    """The submitter status route is per-submitter for everyone; owners review via /review."""
    case_id = submit(client, MEMBER_A).json()["case_id"]
    response = client.get(f"{BASE}/cases/{case_id}", headers=owner_headers())
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "CASE_STATUS_NOT_VISIBLE"}


# --- the marker itself -------------------------------------------------------------


def test_member_writable_marker_opens_post_only(supabase):
    probe_router = APIRouter(dependencies=[Depends(member_auth.owner_or_member_write)])

    @probe_router.post("/probe")
    @member_auth.member_writable
    def probe_post():
        return {"ok": True}

    @probe_router.put("/probe")
    @member_auth.member_writable
    def probe_put():
        return {"ok": True}

    @probe_router.get("/probe")
    @member_auth.member_writable
    def probe_get():
        return {"ok": True}

    @probe_router.post("/unmarked")
    def unmarked():
        return {"ok": True}

    probe = FastAPI()
    probe.include_router(probe_router)
    probe_client = TestClient(probe)
    assert probe_client.post("/probe", headers=MEMBER_A).status_code == 200
    for method, path in (("PUT", "/probe"), ("GET", "/probe"), ("POST", "/unmarked")):
        response = probe_client.request(method, path, headers=MEMBER_A)
        assert response.status_code == 403, (method, path)
        assert response.json() == OWNER_ACCESS_REQUIRED_BODY
    for method, path in (
        ("PUT", "/probe"),
        ("GET", "/probe"),
        ("POST", "/unmarked"),
        ("POST", "/probe"),
    ):
        assert (
            probe_client.request(method, path, headers=owner_headers()).status_code
            == 200
        )


def test_member_readable_marker_does_not_open_writes_on_the_read_dependency(supabase):
    """``owner_or_member_read`` ignores ``@member_writable`` entirely."""
    probe_router = APIRouter(dependencies=[Depends(member_auth.owner_or_member_read)])

    @probe_router.post("/probe")
    @member_auth.member_writable
    def probe_post():
        return {"ok": True}

    probe = FastAPI()
    probe.include_router(probe_router)
    assert TestClient(probe).post("/probe", headers=MEMBER_A).status_code == 403


def test_principal_role():
    assert member_auth.principal_role({"auth_type": "owner_session"}) == "owner"
    assert member_auth.principal_role({"auth_type": "api_key"}) == "api_key"
    assert (
        member_auth.principal_role({"role": "member", "auth_type": "supabase_member"})
        == "member"
    )
    assert member_auth.principal_role({"actor": "x"}) == "unknown"


# --- checker round 1: provisional snapshots, trusted type, input hygiene ------------

TAXON_PAYLOAD = {"accepted_name": "SYNTHETIC taxon", "rank": "species"}


def register_as(client, headers, object_id, object_type, payload):
    return client.post(
        f"{BASE}/objects",
        json={"object_id": object_id, "object_type": object_type, "payload": payload},
        headers=headers,
    )


def test_member_snapshot_cannot_squat_an_owner_registration(store, client, supabase):
    squat = register_as(client, MEMBER_A, "taxon:1", "lexicon", TAXON_PAYLOAD)
    assert squat.status_code == 201, squat.text
    # Another member claiming a different type is not blocked either.
    other = register_as(client, MEMBER_B, "taxon:1", "taxonomy", TAXON_PAYLOAD)
    assert other.status_code == 201, other.text

    owner = register_as(client, owner_headers(), "taxon:1", "taxonomy", TAXON_PAYLOAD)
    assert owner.status_code == 201, owner.text
    assert owner.json()["object_type"] == "taxonomy"
    assert owner.json()["registered_by_role"] == "owner_session"
    assert owner.json()["version_hash"] == squat.json()["version_hash"]
    # The canonical namespace holds exactly the owner's version.
    versions = store.repository().list_object_versions("taxon:1")
    assert [(v.object_type.value, v.registered_by_role) for v in versions] == [
        ("taxonomy", "owner_session")
    ]
    # A later member registration returns the canonical version and writes nothing canonical.
    again = register_as(client, MEMBER_A, "taxon:1", "lexicon", TAXON_PAYLOAD)
    assert again.status_code == 201
    assert len(store.repository().list_object_versions("taxon:1")) == 1


def test_nobody_can_address_the_member_snapshot_namespace(file_store, client, supabase):
    for headers in (owner_headers(), MEMBER_A, API_KEY):
        response = register_as(
            client, headers, "member-snapshot:lexicon:taxon:1", "lexicon", {"d": 1}
        )
        assert response.status_code == 422, headers
        assert response.json()["detail"] == {"code": "OBJECT_ID_RESERVED"}
    body = case_body("0" * 64, object_id="member-snapshot:lexicon:x")
    assert (
        client.post(f"{BASE}/cases", json=body, headers=owner_headers()).status_code
        == 422
    )


def _lexicon_claim_on(client, object_id, payload, headers=MEMBER_A):
    version = register_as(client, headers, object_id, "lexicon", payload).json()[
        "version_hash"
    ]
    return client.post(
        f"{BASE}/cases",
        json=case_body(version, "Typo in the name.", object_id=object_id),
        headers=headers,
    )


def test_member_typed_lexicon_on_an_owner_registered_scientific_object_takes_the_trusted_type(
    store, client, supabase
):
    assert (
        register_as(
            client, owner_headers(), "taxon:1", "taxonomy", TAXON_PAYLOAD
        ).status_code
        == 201
    )
    response = _lexicon_claim_on(client, "taxon:1", TAXON_PAYLOAD)
    assert response.status_code == 201, response.text
    case = store.repository().get_case(response.json()["case_id"])
    assert case.object_type.value == "taxonomy"
    assert case.object_type_source == "registered"
    assert case.disposition.value == "needs_taxonomic_review"
    detail = client.get(f"{REVIEW}/{case.case_id}", headers=owner_headers()).json()
    assert "accept_trivial" not in detail["allowed_decisions"]
    refused = client.post(
        f"{BASE}/cases/{case.case_id}/accept-trivial",
        json={"corrected_payload": {"accepted_name": "x"}},
        headers=owner_headers(),
    )
    assert refused.status_code == 409


def test_member_typed_lexicon_without_a_registered_object_is_never_accept_trivial_eligible(
    store, client, supabase
):
    response = _lexicon_claim_on(client, "taxon:1", TAXON_PAYLOAD)
    assert response.status_code == 201, response.text
    case = store.repository().get_case(response.json()["case_id"])
    assert case.object_type_source == "member_claimed"
    assert case.disposition.value == "needs_scientific_review"
    assert case.review_lane.value == "scientific"
    detail = client.get(f"{REVIEW}/{case.case_id}", headers=owner_headers()).json()
    assert detail["object_version_provisional"] is True
    assert detail["allowed_decisions"] == ["reject", "needs_governed_review"]
    refused = client.post(
        f"{REVIEW}/{case.case_id}/decision",
        json={
            "decision": "accept_trivial",
            "corrected_payload": {"accepted_name": "x"},
        },
        headers=owner_headers(),
    )
    assert refused.status_code == 409, refused.text
    # Even after the owner registers the same content, the member-claimed case stays governed.
    register_as(client, owner_headers(), "taxon:1", "lexicon", TAXON_PAYLOAD)
    assert (
        "accept_trivial"
        not in client.get(f"{REVIEW}/{case.case_id}", headers=owner_headers()).json()[
            "allowed_decisions"
        ]
    )


FORMAT_CHARACTERS = ["\u202e", "\u200b", "\u2066", "\ufeff", "\u200e"]


@pytest.mark.parametrize("char", FORMAT_CHARACTERS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "field", ["statement", "page_context", "proposed_replacement", "citation"]
)
def test_member_text_with_format_characters_is_refused(
    file_store, client, supabase, char, field
):
    version = register(client, MEMBER_A).json()["version_hash"]
    body = case_body(version, **{field: f"looks fine{char}evil"})
    response = client.post(f"{BASE}/cases", json=body, headers=MEMBER_A)
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "MEMBER_TEXT_FORMAT_CHARACTERS"}
    assert (
        file_store.repository().list_cases(
            status=None, object_type=None, limit=5, before=None
        )
        == []
    )


@pytest.mark.parametrize("char", FORMAT_CHARACTERS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "shape",
    [
        lambda c: {"definition": f"a{c}b"},
        lambda c: {f"key{c}": "value"},
        lambda c: {"nested": [{"deeper": [f"x{c}"]}]},
    ],
    ids=["value", "key", "nested"],
)
def test_member_snapshot_with_format_characters_is_refused(
    file_store, client, supabase, char, shape
):
    response = register(client, MEMBER_A, payload=shape(char))
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "OBJECT_PAYLOAD_FORMAT_CHARACTERS"}
    assert file_store.files_written() == []


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_member_snapshot_with_non_finite_number_is_refused(
    store, client, supabase, literal
):
    response = client.post(
        f"{BASE}/objects",
        content=(
            '{"object_id":"lexicon:labellum","object_type":"lexicon",'
            f'"payload":{{"value":{literal}}}}}'
        ),
        headers={**MEMBER_A, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "OBJECT_PAYLOAD_NON_FINITE_NUMBER"}
    assert store.repository().list_object_versions("lexicon:labellum") == []
    store.restart()
    assert store.repository().list_object_versions("lexicon:labellum") == []


@pytest.mark.parametrize(
    "payload_fragment",
    ['"value":"\\ud800"', '"\\ud800":"value"'],
    ids=["value", "key"],
)
def test_member_snapshot_with_lone_surrogate_is_refused(
    store, client, supabase, payload_fragment
):
    response = client.post(
        f"{BASE}/objects",
        content=(
            '{"object_id":"lexicon:labellum","object_type":"lexicon",'
            f'"payload":{{{payload_fragment}}}}}'
        ),
        headers={**MEMBER_A, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "OBJECT_PAYLOAD_INVALID_UNICODE"}
    assert store.repository().list_object_versions("lexicon:labellum") == []
    store.restart()
    assert store.repository().list_object_versions("lexicon:labellum") == []


def test_member_snapshot_nesting_is_capped(file_store, client, supabase):
    def nested(depth):
        value: dict = {"leaf": 1}
        for _ in range(depth - 1):
            value = {"n": value}
        return value

    at_cap = register(
        client, MEMBER_A, payload=nested(routes.MEMBER_OBJECT_PAYLOAD_MAX_DEPTH)
    )
    assert at_cap.status_code == 201, at_cap.text
    too_deep = register(
        client, MEMBER_A, payload=nested(routes.MEMBER_OBJECT_PAYLOAD_MAX_DEPTH + 1)
    )
    assert too_deep.status_code == 422
    assert too_deep.json()["detail"] == {"code": "OBJECT_PAYLOAD_TOO_DEEP"}
    lists: list = [1]
    for _ in range(routes.MEMBER_OBJECT_PAYLOAD_MAX_DEPTH):
        lists = [lists]
    in_lists = register(client, MEMBER_A, payload={"l": lists})
    assert in_lists.status_code == 422
    assert in_lists.json()["detail"] == {"code": "OBJECT_PAYLOAD_TOO_DEEP"}


def test_member_cannot_set_source_partner(file_store, client, supabase):
    version = register(client, MEMBER_A).json()["version_hash"]
    response = client.post(
        f"{BASE}/cases",
        json=case_body(version, source_partner_id="SYNTHETIC-partner"),
        headers=MEMBER_A,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "MEMBER_SOURCE_PARTNER_NOT_ACCEPTED"}
    # The owner keeps partner routing.
    assert register(client, owner_headers()).status_code == 201
    owner = client.post(
        f"{BASE}/cases",
        json=case_body(version, source_partner_id="SYNTHETIC-partner"),
        headers=owner_headers(),
    )
    assert owner.status_code == 201
    assert owner.json()["case"]["review_lane"] == "source_partner"


def test_owner_review_labels_who_submitted_each_case(store, client, supabase):
    member_case = submit(client, MEMBER_A).json()["case_id"]
    owner_case = submit(client, owner_headers(), "Owner report.").json()["case"][
        "case_id"
    ]
    items = {
        item["case_id"]: item
        for item in client.get(REVIEW, headers=owner_headers()).json()["items"]
    }
    assert items[member_case]["submitter_role"] == "member"
    assert items[member_case]["object_type_source"] == "member_claimed"
    assert items[owner_case]["submitter_role"] == "owner_session"
    detail = client.get(f"{REVIEW}/{member_case}", headers=owner_headers()).json()
    assert detail["case"]["submitter_role"] == "member"


@pytest.mark.parametrize("switch", ["feedback", "reads"])
def test_switches_are_checked_before_any_supabase_call(
    file_store, client, supabase, monkeypatch, switch
):
    if switch == "feedback":
        monkeypatch.delenv(member_auth.MEMBER_FEEDBACK_ENV, raising=False)
    else:
        monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    for token in (TOKEN_A, TOKEN_REJECTED):
        for method, url, body in _member_calls("0" * 64):
            response = client.request(method, url, json=body, headers=bearer(token))
            assert response.status_code == 403, (method, url)
            assert response.json() == FEEDBACK_DISABLED_BODY
    assert supabase.call_count == 0
    # Anonymous and forged owner-shaped bearers keep their 401, still without Supabase.
    assert register(client, {}).status_code == 401
    assert register(client, bearer("abc." + "0" * 64)).status_code == 401
    assert supabase.call_count == 0
