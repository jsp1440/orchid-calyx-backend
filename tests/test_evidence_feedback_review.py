"""Owner review queue and decisions for submitted evidence feedback (J12).

Drives the real ``app.main`` application with real owner-session, API-key and
(mocked-Supabase) member authentication. Store-dependent tests run against the
file store and the PostgreSQL store (``tests/evidence_feedback_stores.py``).
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import member_auth
from app.evidence_feedback import EvidenceFeedbackService, routes
from app.evidence_feedback.models import content_hash
from app.evidence_feedback.postgres_repository import (
    SCHEMA,
    PostgresEvidenceFeedbackRepository,
)
from app.evidence_feedback.review import actor_ref
from app.main import app
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token
from tests.evidence_feedback_stores import STORES, make_store, test_database_url

TEST_API_KEY = "local-test-api-key-not-a-credential"
TEST_SESSION_SECRET = "local-test-session-secret-not-a-credential"
SUBMITTER_EMAIL = "submitter.private@example.org"
BASE = "/api/evidence-feedback"
REVIEW = f"{BASE}/review/cases"
MEMBER_UUID = "33333333-3333-3333-3333-333333333333"


class TickClock:
    """Deterministic clock: each call advances one second (or stays put)."""

    def __init__(self, *, step_seconds: int = 1) -> None:
        self.now = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
        self.step = timedelta(seconds=step_seconds)

    def __call__(self) -> str:
        value = self.now.isoformat()
        self.now += self.step
        return value


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.delenv("OC_MEMBER_READS_ENABLED", raising=False)
    member_auth.clear_member_token_cache()
    yield
    member_auth.clear_member_token_cache()


@pytest.fixture(params=STORES)
def store(request, tmp_path, monkeypatch):
    return make_store(request.param, tmp_path, monkeypatch)


@pytest.fixture
def file_store(tmp_path, monkeypatch):
    return make_store("file", tmp_path, monkeypatch)


def use_clock(monkeypatch, clock) -> None:
    monkeypatch.setattr(
        routes,
        "_service",
        lambda: EvidenceFeedbackService(routes._repository(), clock=clock),
    )


@pytest.fixture
def clock(monkeypatch) -> TickClock:
    tick = TickClock()
    use_clock(monkeypatch, tick)
    return tick


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def owner_headers(owner: str = "owner") -> dict[str, str]:
    return bearer(str(create_owner_session_token(owner)["token"]))


def reviewer_headers() -> dict[str, str]:
    return owner_headers("owner")


def submitter_headers() -> dict[str, str]:  # a second, email-named identity
    return owner_headers(SUBMITTER_EMAIL)


def member_jwt(marker: str = "a") -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"sub": MEMBER_UUID, "exp": int(time.time() + 3600), "m": marker}
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.sig"


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"id": MEMBER_UUID, "email": "member@example.org"}
    mock = Mock(return_value=response)
    monkeypatch.setattr("app.university.learner_auth.requests.get", mock)
    return mock


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def submit(
    client: TestClient,
    *,
    object_id: str = "lexicon:labellum",
    object_type: str = "lexicon",
    payload: dict | None = None,
    statement: str = "Petal is misspelled.",
    feedback_class: str = "suggest_correction",
    defect_kind: str | None = "typo",
    proposed_replacement: str | None = "a modified petal",
    severity: str = "normal",
    headers: dict[str, str] | None = None,
) -> dict:
    headers = headers or submitter_headers()
    registered = client.post(
        f"{BASE}/objects",
        json={
            "object_id": object_id,
            "object_type": object_type,
            "payload": payload or {"term": "labellum", "definition": "a modified petel"},
        },
        headers=headers,
    )
    assert registered.status_code == 201, registered.text
    version = registered.json()
    response = client.post(
        f"{BASE}/cases",
        json={
            "object_id": object_id,
            "object_version_hash": version["version_hash"],
            "object_type": object_type,
            "page_context": f"/{object_type}/{object_id}",
            "feedback_class": feedback_class,
            "statement": statement,
            "proposed_replacement": proposed_replacement,
            "citation": None,
            "source_partner_id": None,
            "defect_kind": defect_kind,
            "severity": severity,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def decide(client: TestClient, case_id: str, body: dict, headers=None):
    return client.post(f"{REVIEW}/{case_id}/decision", json=body, headers=headers or reviewer_headers())


def scientific_case(client: TestClient, statement: str = "Wrong genus shown.") -> dict:
    return submit(
        client,
        object_id="matrix:run-1",
        object_type="matrix_identification",
        payload={"candidate": "Dracula vampira", "rank": 1},
        statement=statement,
        feedback_class="challenge",
        defect_kind=None,
        proposed_replacement=None,
        severity="high",
    )["case"]


# --- queue --------------------------------------------------------------------


def test_queue_lists_newest_first_with_triage_fields_and_no_raw_identity(store, clock, client):
    first = submit(client)["case"]
    second = scientific_case(client)

    response = client.get(REVIEW, headers=reviewer_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 25
    assert body["next_cursor"] is None
    assert [item["case_id"] for item in body["items"]] == [second["case_id"], first["case_id"]]
    item = body["items"][0]
    assert set(item) == {
        "case_id", "status", "disposition", "review_lane", "object_type", "object_id",
        "object_version_hash", "feedback_class", "severity", "defect_kind", "page_context",
        "statement_preview", "created_at", "updated_at", "duplicate_count", "submitter_ref",
    }
    assert item["object_type"] == "matrix_identification"
    assert item["severity"] == "high"
    assert item["status"] == "pending_review"
    assert item["duplicate_count"] == 0
    assert item["submitter_ref"] == actor_ref(SUBMITTER_EMAIL)
    assert item["submitter_ref"].startswith("actor-")
    assert SUBMITTER_EMAIL not in response.text
    assert "submitter_id" not in response.text


def test_empty_store_lists_no_cases(store, client):
    response = client.get(REVIEW, headers=reviewer_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None, "limit": 25}


def test_cursor_pages_are_complete_stable_and_ordered_even_with_equal_timestamps(
    store, client, monkeypatch
):
    use_clock(monkeypatch, TickClock(step_seconds=0))  # every case shares created_at
    ids = {
        submit(client, statement=f"Problem number {index}.")["case"]["case_id"]
        for index in range(5)
    }
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(REVIEW, params=params, headers=reviewer_headers())
        assert page.status_code == 200
        body = page.json()
        assert len(body["items"]) <= 2
        seen.extend(item["case_id"] for item in body["items"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == ids
    assert seen == sorted(ids, reverse=True)  # created_at tie broken by case id
    # Re-reading the first page gives the same answer.
    again = client.get(REVIEW, params={"limit": 2}, headers=reviewer_headers()).json()
    assert [item["case_id"] for item in again["items"]] == seen[:2]


def test_limit_and_cursor_are_bounded_and_validated(store, client):
    for params in ({"limit": 0}, {"limit": 101}, {"limit": "x"}):
        assert client.get(REVIEW, params=params, headers=reviewer_headers()).status_code == 422
    bad = client.get(REVIEW, params={"cursor": "not-a-cursor"}, headers=reviewer_headers())
    assert bad.status_code == 422
    assert bad.json()["detail"] == {"code": "INVALID_REVIEW_CURSOR"}
    assert client.get(REVIEW, params={"limit": 100}, headers=reviewer_headers()).status_code == 200


def test_status_and_object_type_filters(store, clock, client):
    lexicon = submit(client)["case"]
    matrix = scientific_case(client)
    assert decide(client, matrix["case_id"], {"decision": "reject", "reason": "Out of scope."}).status_code == 200

    def ids(**params):
        response = client.get(REVIEW, params=params, headers=reviewer_headers())
        assert response.status_code == 200
        return [item["case_id"] for item in response.json()["items"]]

    assert ids(status="pending_review") == [lexicon["case_id"]]
    assert ids(status="resolved") == [matrix["case_id"]]
    assert ids(status="governed_review_required") == []
    assert ids(object_type="lexicon") == [lexicon["case_id"]]
    assert ids(object_type="matrix_identification", status="resolved") == [matrix["case_id"]]
    assert ids(object_type="taxonomy") == []
    assert client.get(REVIEW, params={"status": "bogus"}, headers=reviewer_headers()).status_code == 422
    assert client.get(REVIEW, params={"object_type": "bogus"}, headers=reviewer_headers()).status_code == 422


# --- detail -------------------------------------------------------------------


def test_detail_has_event_history_object_version_and_duplicate_count(store, clock, client):
    case = submit(client)["case"]
    duplicate = submit(client)  # identical submission is suppressed, not a new case
    assert duplicate["created"] is False

    response = client.get(f"{REVIEW}/{case['case_id']}", headers=reviewer_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["case"]["case_id"] == case["case_id"]
    assert body["case"]["statement"] == "Petal is misspelled."
    assert body["case"]["submitter_ref"] == actor_ref(SUBMITTER_EMAIL)
    assert "submitter_id" not in body["case"] and "reviewer_id" not in body["case"]
    assert body["duplicate_count"] == 1
    assert [event["event"] for event in body["events"]] == [
        "case_submitted",
        "duplicate_submission_suppressed",
    ]
    assert all(event["actor_ref"] == actor_ref(SUBMITTER_EMAIL) for event in body["events"])
    assert body["object_version"]["version_hash"] == case["object_version_hash"]
    assert body["object_version"]["payload"] == {"term": "labellum", "definition": "a modified petel"}
    assert body["object_version_available"] is True
    assert body["resulting_object_version"] is None
    assert body["allowed_decisions"] == ["reject", "needs_governed_review", "accept_trivial"]
    assert "never publish" in body["publication_boundary"]
    assert SUBMITTER_EMAIL not in response.text
    listed = client.get(REVIEW, headers=reviewer_headers()).json()["items"]
    assert listed[0]["duplicate_count"] == 1

    missing = client.get(f"{REVIEW}/efc-does-not-exist", headers=reviewer_headers())
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "CASE_NOT_FOUND"}


# --- decisions ----------------------------------------------------------------


def test_reject_resolves_appends_one_event_and_is_idempotent(store, clock, client):
    case = scientific_case(client)
    body = {"decision": "reject", "reason": "The displayed candidate is correct."}

    first = decide(client, case["case_id"], body)
    repeat = decide(client, case["case_id"], body)

    assert first.status_code == 200 and repeat.status_code == 200
    assert first.json()["idempotent"] is False
    assert repeat.json()["idempotent"] is True
    decided = first.json()["case"]
    assert decided["status"] == "resolved"
    assert decided["disposition"] == "correction_rejected"
    assert decided["resolution"] == "The displayed candidate is correct."
    assert decided["reviewer_ref"] == actor_ref("owner")
    assert decided["resulting_version_hash"] is None
    assert first.json()["allowed_decisions"] == []
    detail = client.get(f"{REVIEW}/{case['case_id']}", headers=reviewer_headers()).json()
    events = [event["event"] for event in detail["events"]]
    assert events == ["case_submitted", "owner_decision_rejected"]
    assert detail["events"][-1]["details"]["reason"] == "The displayed candidate is correct."
    assert detail["events"][-1]["details"]["previous_status"] == "pending_review"

    conflicting = decide(client, case["case_id"], {"decision": "reject", "reason": "Other."})
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"] == {
        "code": "INVALID_CASE_TRANSITION",
        "current_status": "resolved",
        "decision": "reject",
    }
    routed = decide(client, case["case_id"], {"decision": "needs_governed_review", "note": "n"})
    assert routed.status_code == 409
    # The submitter sees the owner's outcome through the existing status route.
    status = client.get(f"{BASE}/cases/{case['case_id']}", headers=submitter_headers()).json()
    assert status["status"] == "resolved"
    assert status["disposition"] == "correction_rejected"


def test_governed_review_keeps_case_unresolved_and_blocks_the_trivial_path(store, clock, client):
    case = submit(client)["case"]  # lexicon typo: eligible for the trivial path
    note = {"decision": "needs_governed_review", "note": "Definition wording needs a botanist."}

    routed = decide(client, case["case_id"], note)
    repeat = decide(client, case["case_id"], note)

    assert routed.status_code == 200 and repeat.status_code == 200
    assert routed.json()["idempotent"] is False and repeat.json()["idempotent"] is True
    assert routed.json()["case"]["status"] == "governed_review_required"
    assert routed.json()["case"]["disposition"] == "auto_correctable"  # triage unchanged
    assert routed.json()["case"]["resolution"] is None
    assert routed.json()["allowed_decisions"] == ["reject"]
    other_note = decide(client, case["case_id"], {"decision": "needs_governed_review", "note": "x"})
    assert other_note.status_code == 409

    accept = decide(
        client,
        case["case_id"],
        {"decision": "accept_trivial", "corrected_payload": {"term": "labellum", "definition": "a modified petal"}},
    )
    assert accept.status_code == 409
    assert accept.json()["detail"]["code"] == "INVALID_CASE_TRANSITION"
    # The pre-existing reviewer route honours the routing too.
    legacy = client.post(
        f"{BASE}/cases/{case['case_id']}/accept-trivial",
        json={"corrected_payload": {"term": "labellum", "definition": "a modified petal"}},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert legacy.status_code == 409
    assert legacy.json()["detail"] == {"code": "GOVERNED_REVIEW_REQUIRED"}
    assert len(store.repository().list_object_versions("lexicon:labellum")) == 1

    closed = decide(client, case["case_id"], {"decision": "reject", "reason": "Botanist declined."})
    assert closed.status_code == 200
    assert closed.json()["case"]["status"] == "resolved"
    events = [e["event"] for e in client.get(f"{REVIEW}/{case['case_id']}", headers=reviewer_headers()).json()["events"]]
    assert events == ["case_submitted", "owner_decision_needs_governed_review", "owner_decision_rejected"]


def test_accept_trivial_reuses_the_existing_path_and_is_idempotent(store, clock, client):
    case = submit(client)["case"]
    corrected = {"term": "labellum", "definition": "a modified petal"}
    body = {"decision": "accept_trivial", "corrected_payload": corrected}

    first = decide(client, case["case_id"], body)
    repeat = decide(client, case["case_id"], body)

    assert first.status_code == 200 and repeat.status_code == 200
    assert first.json()["idempotent"] is False and repeat.json()["idempotent"] is True
    decided = first.json()["case"]
    assert decided["status"] == "resolved"
    assert decided["disposition"] == "correction_accepted"
    assert decided["resolution"] == "deterministic trivial correction accepted"
    assert decided["resulting_version_hash"] == content_hash(corrected)
    detail = client.get(f"{REVIEW}/{case['case_id']}", headers=reviewer_headers()).json()
    assert [e["event"] for e in detail["events"]] == ["case_submitted", "correction_accepted"]
    assert detail["resulting_object_version"]["payload"] == corrected
    assert detail["resulting_object_version"]["previous_version_hash"] == case["object_version_hash"]
    assert len(store.repository().list_object_versions("lexicon:labellum")) == 2

    different = decide(client, case["case_id"], {"decision": "accept_trivial", "corrected_payload": {"x": 1}})
    assert different.status_code == 409
    assert decide(client, case["case_id"], {"decision": "reject", "reason": "r"}).status_code == 409


def test_scientific_case_cannot_take_the_trivial_path_and_nothing_is_written(store, clock, client):
    case = scientific_case(client)
    detail = client.get(f"{REVIEW}/{case['case_id']}", headers=reviewer_headers()).json()
    assert detail["allowed_decisions"] == ["reject", "needs_governed_review"]

    refused = decide(
        client, case["case_id"], {"decision": "accept_trivial", "corrected_payload": {"candidate": "X"}}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "GOVERNED_REVIEW_REQUIRED"}
    repository = store.repository()
    assert len(repository.list_object_versions("matrix:run-1")) == 1
    unchanged = repository.get_case(case["case_id"])
    assert unchanged.status.value == "pending_review"
    assert [e["event"] for e in repository.list_events(case["case_id"])] == ["case_submitted"]
    # Routing a scientific correction never creates a version either.
    assert decide(client, case["case_id"], {"decision": "needs_governed_review", "note": "n"}).status_code == 200
    assert len(repository.list_object_versions("matrix:run-1")) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "reject"},
        {"decision": "reject", "reason": "   "},
        {"decision": "reject", "reason": "r", "corrected_payload": {}},
        {"decision": "needs_governed_review"},
        {"decision": "needs_governed_review", "note": "n", "reason": "r"},
        {"decision": "accept_trivial"},
        {"decision": "accept_trivial", "corrected_payload": {}, "note": "n"},
        {"decision": "publish", "reason": "r"},
        {"decision": "reject", "reason": "r", "unexpected": True},
        {"decision": "reject", "reason": "r" * 4001},
    ],
)
def test_decision_body_must_match_the_decision(file_store, clock, client, body):
    case = submit(client)["case"]
    response = decide(client, case["case_id"], body)
    assert response.status_code == 422
    assert file_store.repository().get_case(case["case_id"]).status.value == "pending_review"


def test_decision_on_unknown_case_is_404(store, client):
    response = decide(client, "efc-does-not-exist", {"decision": "reject", "reason": "r"})
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "CASE_NOT_FOUND"}


# --- authentication matrix ------------------------------------------------------


def _review_calls(case_id: str):
    return [
        ("GET", REVIEW, None),
        ("GET", f"{REVIEW}/{case_id}", None),
        ("POST", f"{REVIEW}/{case_id}/decision", {"decision": "reject", "reason": "r"}),
    ]


def test_only_the_owner_session_can_review(file_store, clock, client, supabase):
    case_id = submit(client)["case"]["case_id"]
    member_body = {"detail": {"code": "OWNER_ACCESS_REQUIRED", "message": "This view is limited to owner access"}}
    for method, url, body in _review_calls(case_id):
        anonymous = client.request(method, url, json=body)
        assert anonymous.status_code == 401, (method, url)
        api_key = client.request(method, url, json=body, headers={"X-API-Key": TEST_API_KEY})
        assert api_key.status_code == 403, (method, url)
        assert api_key.json()["detail"]["code"] == "OWNER_SESSION_REQUIRED"
        wrong_key = client.request(method, url, json=body, headers={"X-API-Key": "wrong"})
        assert wrong_key.status_code == 401, (method, url)
        member = client.request(method, url, json=body, headers=bearer(member_jwt()))
        assert member.status_code == 403, (method, url)
        assert member.json() == member_body
        forged = client.request(method, url, json=body, headers=bearer("abc." + "0" * 64))
        assert forged.status_code == 401, (method, url)
    # Nothing above changed the case.
    assert file_store.repository().get_case(case_id).status.value == "pending_review"

    cookie_client = TestClient(app)
    cookie_client.cookies.set(OWNER_SESSION_COOKIE, str(create_owner_session_token("owner")["token"]))
    for method, url, body in _review_calls(case_id):
        assert cookie_client.request(method, url, json=body).status_code == 200, (method, url)


def test_member_403_is_identical_for_existing_and_missing_cases(file_store, clock, client, supabase):
    case_id = submit(client)["case"]["case_id"]
    bodies = {
        client.request(method, url, json=body, headers=bearer(member_jwt())).content
        for case in (case_id, "efc-missing")
        for method, url, body in _review_calls(case)
    }
    assert len(bodies) == 1


def test_member_rejected_when_member_reads_disabled(file_store, client, supabase, monkeypatch):
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    assert client.get(REVIEW, headers=bearer(member_jwt(marker="off"))).status_code == 401


# --- store parity and indexing ------------------------------------------------------


def _scenario(client: TestClient) -> dict:
    """One scripted review session; returns every review response it produced."""

    lexicon = submit(client)["case"]
    submit(client)  # duplicate
    matrix = scientific_case(client)
    other = scientific_case(client, statement="Second opinion needed.")
    responses = {
        "accept": decide(client, lexicon["case_id"], {"decision": "accept_trivial", "corrected_payload": {"term": "labellum", "definition": "a modified petal"}}).json(),
        "reject": decide(client, matrix["case_id"], {"decision": "reject", "reason": "Correct as shown."}).json(),
        "route": decide(client, other["case_id"], {"decision": "needs_governed_review", "note": "Send to a specialist."}).json(),
        "repeat": decide(client, other["case_id"], {"decision": "needs_governed_review", "note": "Send to a specialist."}).json(),
        "invalid": decide(client, matrix["case_id"], {"decision": "needs_governed_review", "note": "late"}).json(),
    }
    pages = []
    cursor = None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(REVIEW, params=params, headers=reviewer_headers()).json()
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            break
    responses["pages"] = pages
    responses["filtered"] = client.get(REVIEW, params={"status": "resolved"}, headers=reviewer_headers()).json()
    responses["details"] = [
        client.get(f"{REVIEW}/{case_id}", headers=reviewer_headers()).json()
        for case_id in (lexicon["case_id"], matrix["case_id"], other["case_id"])
    ]
    return responses


@pytest.mark.requires_postgres
def test_file_and_postgres_stores_answer_the_review_api_identically(tmp_path, monkeypatch, client):
    database_url = test_database_url()
    results = {}
    for kind in ("file", "postgres"):
        if kind == "postgres":  # the file store unset the database variables
            monkeypatch.setenv("TEST_DATABASE_URL", database_url)
        make_store(kind, tmp_path / kind, monkeypatch)
        use_clock(monkeypatch, TickClock())
        results[kind] = _scenario(client)
    assert results["file"] == results["postgres"]
    assert len(results["file"]["pages"]) == 2
    assert results["file"]["repeat"]["idempotent"] is True
    assert results["file"]["invalid"]["detail"]["code"] == "INVALID_CASE_TRANSITION"


@pytest.mark.requires_postgres
def test_postgres_review_listing_uses_the_review_order_index(tmp_path, monkeypatch):
    store = make_store("postgres", tmp_path, monkeypatch)
    PostgresEvidenceFeedbackRepository(store.database_url)
    with psycopg.connect(store.database_url) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL enable_seqscan = off")
        cur.execute(
            f"EXPLAIN SELECT record_json FROM {SCHEMA}.cases "
            "ORDER BY (((record_json::jsonb)->>'created_at') COLLATE \"C\") DESC, "
            "(case_key COLLATE \"C\") DESC LIMIT 26"
        )
        plan = "\n".join(row[0] for row in cur.fetchall())
    assert "cases_review_order_idx" in plan, plan


@pytest.mark.requires_postgres
def test_existing_postgres_tables_gain_the_review_index_additively(tmp_path, monkeypatch, client):
    store = make_store("postgres", tmp_path, monkeypatch)
    use_clock(monkeypatch, TickClock())
    case_id = submit(client)["case"]["case_id"]
    # Simulate a database provisioned before the review index existed.
    with psycopg.connect(store.database_url) as conn, conn.cursor() as cur:
        cur.execute(f"DROP INDEX {SCHEMA}.cases_review_order_idx")
    PostgresEvidenceFeedbackRepository(store.database_url)  # a restarted process
    with psycopg.connect(store.database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.cases_review_order_idx",))
        assert cur.fetchone()[0] is not None
    store.restart()
    listed = client.get(REVIEW, headers=reviewer_headers()).json()["items"]
    assert [item["case_id"] for item in listed] == [case_id]  # data kept
