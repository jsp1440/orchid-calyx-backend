"""PostgreSQL-only guarantees of the durable evidence-feedback store.

Runs against the disposable test database (TEST_DATABASE_URL, then
DATABASE_URL). ``requires_postgres`` skips off-runner with the driver's reason
and fails in CI when that database is unusable.
"""

from __future__ import annotations

import threading
import time

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.evidence_feedback import (
    EvidenceFeedbackService,
    FeedbackClass,
    ObjectType,
    routes,
)
from app.evidence_feedback.postgres_repository import (
    SCHEMA,
    SCHEMA_STATEMENTS,
    PostgresEvidenceFeedbackRepository,
)
from app.evidence_feedback.repository import (
    EvidenceFeedbackRepositoryError,
    EvidenceFeedbackStoreUnavailable,
)
from app.member_auth import owner_or_member_write
from tests.evidence_feedback_stores import make_store

pytestmark = pytest.mark.requires_postgres

CLOCK = "2026-09-26T12:00:00+00:00"


@pytest.fixture
def store(tmp_path, monkeypatch):
    return make_store("postgres", tmp_path, monkeypatch)


def _service(repository) -> EvidenceFeedbackService:
    return EvidenceFeedbackService(repository, clock=lambda: CLOCK)


def _count(database_url: str, table: str) -> int:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{table}")
        return int(cur.fetchone()[0])


def _registered(service: EvidenceFeedbackService):
    return service.register_object(
        object_id="lexicon:labellum",
        object_type=ObjectType.LEXICON,
        payload={"term": "labellum", "definition": "a modified petel"},
    )


def _request(version) -> dict:
    return {
        "object_id": version.object_id,
        "object_version_hash": version.version_hash,
        "object_type": ObjectType.LEXICON,
        "page_context": "/lexicon/labellum",
        "feedback_class": FeedbackClass.REPORT_PROBLEM,
        "statement": "Petal is misspelled.",
        "submitter_id": "member-1",
    }


def test_concurrent_duplicate_submissions_from_separate_workers_create_one_case(store):
    """Identical submissions racing through separate processes' repositories."""

    version = _registered(_service(store.repository()))
    workers = 6
    barrier = threading.Barrier(workers)
    results, errors = [], []

    def submit() -> None:
        repository = store.repository()  # one per worker, as separate processes
        lookup = repository.find_by_fingerprint

        def slow_lookup(fingerprint):
            found = lookup(fingerprint)
            time.sleep(0.2)  # widen the check-then-insert window
            return found

        repository.find_by_fingerprint = slow_lookup
        try:
            barrier.wait(timeout=30)
            results.append(_service(repository).submit(**_request(version)))
        except Exception as exc:  # noqa: BLE001 -- surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert len(results) == workers
    created = [result for result in results if result.created]
    assert len(created) == 1
    case_id = created[0].case.case_id
    assert {result.case.case_id for result in results} == {case_id}
    assert {result.duplicate_of for result in results if not result.created} == {case_id}
    assert _count(store.database_url, "cases") == 1
    assert _count(store.database_url, "case_fingerprints") == 1
    events = [event["event"] for event in store.repository().list_events(case_id)]
    assert events.count("case_submitted") == 1
    assert events.count("duplicate_submission_suppressed") == workers - 1


def test_case_is_never_stored_without_its_audit_event(store):
    """A failure after the case write rolls the whole submission back."""

    repository = store.repository()
    version = _registered(_service(repository))
    append_event = repository.append_event

    def failing_append_event(**kwargs):
        append_event(**kwargs)
        raise RuntimeError("simulated failure after the audit event write")

    repository.append_event = failing_append_event
    with pytest.raises(RuntimeError, match="simulated failure"):
        _service(repository).submit(**_request(version))

    restarted = store.repository()
    assert _count(store.database_url, "cases") == 0
    assert _count(store.database_url, "case_events") == 0
    assert _count(store.database_url, "case_fingerprints") == 0
    # The same submission afterwards is a fresh, complete case.
    retried = _service(restarted).submit(**_request(version))
    assert retried.created is True
    assert [e["event"] for e in restarted.list_events(retried.case.case_id)] == [
        "case_submitted"
    ]


def test_failed_trivial_correction_leaves_no_new_version_or_resolution(store):
    repository = store.repository()
    service = _service(repository)
    version = _registered(service)
    submitted = service.submit(
        **{
            **_request(version),
            "feedback_class": FeedbackClass.SUGGEST_CORRECTION,
            "proposed_replacement": "a modified petal",
            "defect_kind": "typo",
        }
    )
    save_case = repository.save_case

    def failing_save_case(case):
        save_case(case)
        raise RuntimeError("simulated failure after resolving the case")

    repository.save_case = failing_save_case
    with pytest.raises(RuntimeError, match="simulated failure"):
        service.accept_trivial_correction(
            case_id=submitted.case.case_id,
            reviewer_id="reviewer-1",
            corrected_payload={"term": "labellum", "definition": "a modified petal"},
        )

    restarted = store.repository()
    assert restarted.get_case(submitted.case.case_id) == submitted.case
    assert restarted.list_object_versions(version.object_id) == [version]


def test_new_repository_instance_sees_everything_a_previous_one_wrote(store):
    """Restart persistence: nothing lives in process memory."""

    first = store.repository()
    service = _service(first)
    version = _registered(service)
    submitted = service.submit(
        **{
            **_request(version),
            "feedback_class": FeedbackClass.SUGGEST_CORRECTION,
            "proposed_replacement": "a modified petal",
            "defect_kind": "typo",
        }
    )
    resolved = service.accept_trivial_correction(
        case_id=submitted.case.case_id,
        reviewer_id="reviewer-1",
        corrected_payload={"term": "labellum", "definition": "a modified petal"},
    )
    del first, service

    restarted = store.repository()
    assert restarted.get_case(resolved.case_id) == resolved
    assert restarted.find_by_fingerprint(resolved.fingerprint) == resolved
    versions = restarted.list_object_versions(version.object_id)
    assert {v.version_hash for v in versions} == {
        version.version_hash,
        resolved.resulting_version_hash,
    }
    assert [e["event"] for e in restarted.list_events(resolved.case_id)] == [
        "case_submitted",
        "correction_accepted",
    ]
    duplicate = _service(restarted).submit(
        **{
            **_request(version),
            "feedback_class": FeedbackClass.SUGGEST_CORRECTION,
            "proposed_replacement": "a modified petal",
            "defect_kind": "typo",
        }
    )
    assert duplicate.created is False
    assert duplicate.duplicate_of == resolved.case_id


def test_http_case_survives_process_restart_and_writes_no_files(store):
    def client() -> TestClient:
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[owner_or_member_write] = lambda: {"actor": "member-1"}
        return TestClient(app)

    before = client()
    version = before.post(
        "/api/evidence-feedback/objects",
        json={"object_id": "lexicon:column", "object_type": "lexicon", "payload": {"d": "x"}},
    ).json()
    created = before.post(
        "/api/evidence-feedback/cases",
        json={
            "object_id": version["object_id"],
            "object_version_hash": version["version_hash"],
            "object_type": "lexicon",
            "page_context": "/lexicon/column",
            "feedback_class": "report_problem",
            "statement": "Needs a citation.",
        },
    )
    assert created.status_code == 201

    store.restart()
    after = client()
    status = after.get(f"/api/evidence-feedback/cases/{created.json()['case']['case_id']}")

    assert status.status_code == 200
    assert status.json()["status"] == "pending_review"
    assert store.files_written() == []


def test_immutability_and_lineage_hold_across_instances(store):
    base = _registered(_service(store.repository()))
    other = _service(store.repository()).register_object(
        object_id=base.object_id,
        object_type=ObjectType.LEXICON,
        payload={"term": "labellum", "definition": "a modified petal"},
        previous_version_hash=base.version_hash,
    )
    assert other.previous_version_hash == base.version_hash
    again = _service(store.repository()).register_object(
        object_id=base.object_id,
        object_type=ObjectType.LEXICON,
        payload=base.payload,
    )
    assert again == base  # original created_at and lineage are kept
    with pytest.raises(EvidenceFeedbackRepositoryError, match="IMMUTABILITY_VIOLATION"):
        _service(store.repository()).register_object(
            object_id=base.object_id,
            object_type=ObjectType.LEXICON,
            payload=base.payload,
            previous_version_hash=other.version_hash,
        )
    assert _count(store.database_url, "object_versions") == 2


def test_database_lost_after_startup_answers_503_not_a_file_fallback(store):
    def client() -> TestClient:
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[owner_or_member_write] = lambda: {"actor": "member-1"}
        return TestClient(app)

    live = client()
    ok = live.post(
        "/api/evidence-feedback/objects",
        json={"object_id": "lexicon:x", "object_type": "lexicon", "payload": {}},
    )
    assert ok.status_code == 201
    repository = routes._POSTGRES_REPOSITORIES[store.database_url]
    repository.database_url = "postgresql://feedback-test@127.0.0.1:9/gone"
    repository.connect_timeout = 2

    lost = live.post(
        "/api/evidence-feedback/objects",
        json={"object_id": "lexicon:x", "object_type": "lexicon", "payload": {}},
    )
    assert lost.status_code == 503
    assert lost.json()["detail"] == {"code": "EVIDENCE_FEEDBACK_DATABASE_UNAVAILABLE"}
    assert store.files_written() == []
    with pytest.raises(EvidenceFeedbackStoreUnavailable):
        repository.get_case("efc-anything")


def test_schema_bootstrap_is_additive_idempotent_and_concurrency_safe(store):
    for statement in SCHEMA_STATEMENTS:
        normalized = " ".join(statement.split()).upper()
        assert normalized.startswith(("CREATE SCHEMA IF NOT EXISTS", "CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS"))
        for destructive in ("DROP ", "TRUNCATE", "ALTER ", "DELETE ", "UPDATE "):
            assert destructive not in normalized

    # Fresh database (disposable test schema only): racing first requests.
    with psycopg.connect(store.database_url) as conn, conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    errors = []
    barrier = threading.Barrier(4)

    def build() -> None:
        try:
            barrier.wait(timeout=30)
            PostgresEvidenceFeedbackRepository(store.database_url)
        except Exception as exc:  # noqa: BLE001 -- surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []

    version = _registered(_service(store.repository()))
    PostgresEvidenceFeedbackRepository(store.database_url)  # re-run: no data loss
    assert store.repository().list_object_versions(version.object_id) == [version]
