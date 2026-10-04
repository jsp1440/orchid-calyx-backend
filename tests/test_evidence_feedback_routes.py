from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.evidence_feedback.routes import router
from app.member_auth import owner_or_member_write
from tests.evidence_feedback_stores import STORES, make_store


@pytest.fixture(params=STORES)
def store(request, tmp_path, monkeypatch):
    return make_store(request.param, tmp_path, monkeypatch)


def client_for(store, actor="member-1", *, restart=False):
    if restart:
        store.restart()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[owner_or_member_write] = lambda: {
        "actor": actor,
        "auth_type": "test",
    }
    return TestClient(app)


def register_object(client, *, object_id, object_type, payload):
    response = client.post(
        "/api/evidence-feedback/objects",
        json={
            "object_id": object_id,
            "object_type": object_type,
            "payload": payload,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_authenticated_lexicon_feedback_survives_new_client(store):
    client = client_for(store)
    version = register_object(
        client,
        object_id="lexicon:labellum",
        object_type="lexicon",
        payload={"definition": "a modified petel"},
    )

    submitted = client.post(
        "/api/evidence-feedback/cases",
        json={
            "object_id": version["object_id"],
            "object_version_hash": version["version_hash"],
            "object_type": "lexicon",
            "page_context": "/lexicon/labellum",
            "feedback_class": "suggest_correction",
            "statement": "Petal is misspelled.",
            "proposed_replacement": "a modified petal",
            "defect_kind": "typo",
        },
    )
    assert submitted.status_code == 201
    case = submitted.json()["case"]
    assert case["disposition"] == "auto_correctable"
    assert case["status"] == "pending_review"

    restarted = client_for(store, restart=True)
    status = restarted.get(f"/api/evidence-feedback/cases/{case['case_id']}")

    assert status.status_code == 200
    assert status.json()["case_id"] == case["case_id"]
    assert status.json()["status"] == "pending_review"
    # With a database configured nothing lands on the local filesystem, even
    # though CALYX_EVIDENCE_FEEDBACK_ROOT is set; the file store writes there.
    if store.kind == "postgres":
        assert store.files_written() == []
    else:
        assert store.files_written()


def test_duplicate_http_submission_is_suppressed(store):
    client = client_for(store)
    version = register_object(
        client,
        object_id="lexicon:column",
        object_type="lexicon",
        payload={"definition": "fused reproductive structure"},
    )
    request = {
        "object_id": version["object_id"],
        "object_version_hash": version["version_hash"],
        "object_type": "lexicon",
        "page_context": "/lexicon/column",
        "feedback_class": "report_problem",
        "statement": "This definition needs a citation.",
    }

    first = client.post("/api/evidence-feedback/cases", json=request)
    second = client.post("/api/evidence-feedback/cases", json=request)

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["duplicate_of"] == first.json()["case"]["case_id"]


def test_submitter_cannot_read_another_identity_case(store):
    owner = client_for(store, actor="member-1")
    version = register_object(
        owner,
        object_id="matrix:episode:7",
        object_type="matrix_identification",
        payload={"candidates": ["taxon:1", "taxon:2"]},
    )
    submitted = owner.post(
        "/api/evidence-feedback/cases",
        json={
            "object_id": version["object_id"],
            "object_version_hash": version["version_hash"],
            "object_type": "matrix_identification",
            "page_context": "/matrix/result/7",
            "feedback_class": "challenge",
            "statement": "The second candidate has the diagnostic trait.",
        },
    )
    case_id = submitted.json()["case"]["case_id"]

    other = client_for(store, actor="member-2")
    response = other.get(f"/api/evidence-feedback/cases/{case_id}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CASE_STATUS_NOT_VISIBLE"


def test_scientific_case_cannot_use_trivial_correction_route(store):
    client = client_for(store)
    version = register_object(
        client,
        object_id="image:annotation:9",
        object_type="image_annotation",
        payload={"taxon_id": "taxon:1"},
    )
    submitted = client.post(
        "/api/evidence-feedback/cases",
        json={
            "object_id": version["object_id"],
            "object_version_hash": version["version_hash"],
            "object_type": "image_annotation",
            "page_context": "/images/9",
            "feedback_class": "image_identification_problem",
            "statement": "This image appears to show another species.",
        },
    )
    case = submitted.json()["case"]
    assert case["disposition"] == "needs_scientific_review"

    response = client.post(
        f"/api/evidence-feedback/cases/{case['case_id']}/accept-trivial",
        json={"corrected_payload": {"taxon_id": "taxon:2"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GOVERNED_REVIEW_REQUIRED"


def test_trivial_route_versions_instead_of_overwriting(store):
    client = client_for(store, actor="reviewer-1")
    original = register_object(
        client,
        object_id="lexicon:sepal",
        object_type="lexicon",
        payload={"definition": "outer floral whorl partt"},
    )
    submitted = client.post(
        "/api/evidence-feedback/cases",
        json={
            "object_id": original["object_id"],
            "object_version_hash": original["version_hash"],
            "object_type": "lexicon",
            "page_context": "/lexicon/sepal",
            "feedback_class": "suggest_correction",
            "statement": "Part has an extra letter.",
            "proposed_replacement": "outer floral whorl part",
            "defect_kind": "typo",
        },
    )
    case_id = submitted.json()["case"]["case_id"]

    accepted = client.post(
        f"/api/evidence-feedback/cases/{case_id}/accept-trivial",
        json={
            "corrected_payload": {
                "definition": "outer floral whorl part",
            }
        },
    )

    assert accepted.status_code == 200
    result = accepted.json()
    assert result["status"] == "resolved"
    assert result["object_version_hash"] == original["version_hash"]
    assert result["resulting_version_hash"] != original["version_hash"]


UNREACHABLE_DATABASE_URL = (
    "postgresql://feedback-test@127.0.0.1:9/unreachable?connect_timeout=2"
)


def test_configured_but_unreachable_database_fails_closed_without_file_fallback(
    tmp_path, monkeypatch
):
    from app.evidence_feedback import routes

    root = tmp_path / "feedback"
    monkeypatch.setenv(routes.FEEDBACK_ROOT_ENV, str(root))
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(routes, "_POSTGRES_REPOSITORIES", {})
    client = client_for(None)

    registered = client.post(
        "/api/evidence-feedback/objects",
        json={"object_id": "lexicon:x", "object_type": "lexicon", "payload": {}},
    )
    submitted = client.post(
        "/api/evidence-feedback/cases",
        json={
            "object_id": "lexicon:x",
            "object_version_hash": "0" * 64,
            "object_type": "lexicon",
            "page_context": "/lexicon/x",
            "feedback_class": "report_problem",
            "statement": "Needs a citation.",
        },
    )
    status = client.get("/api/evidence-feedback/cases/efc-anything")

    for response in (registered, submitted, status):
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "EVIDENCE_FEEDBACK_DATABASE_UNAVAILABLE"
        }
    # No silent fallback: splitting feedback across two stores is data loss.
    assert not root.exists()
    # A failed build is not cached; the next request retries the database.
    assert routes._POSTGRES_REPOSITORIES == {}


@pytest.mark.parametrize(
    ("environment", "expected_warning"),
    [
        ({"RENDER": "true"}, True),
        ({"APP_ENV": "production"}, True),
        ({"ENVIRONMENT": "prod"}, True),
        ({"RENDER": "true", "DATABASE_URL": UNREACHABLE_DATABASE_URL}, False),
        ({"RENDER": "true", "CALYX_EVIDENCE_FEEDBACK_ROOT": "/var/data/fb"}, False),
        ({}, False),
        ({"APP_ENV": "development"}, False),
    ],
)
def test_non_durable_production_store_logs_a_startup_warning(
    monkeypatch, caplog, environment, expected_warning
):
    from app.evidence_feedback import routes

    for name in (
        "RENDER",
        "APP_ENV",
        "ENVIRONMENT",
        "DATABASE_URL",
        "TEST_DATABASE_URL",
        "CALYX_EVIDENCE_FEEDBACK_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level("WARNING", logger=routes.logger.name):
        message = routes.warn_if_non_durable()

    if expected_warning:
        assert message == routes.NON_DURABLE_WARNING
        assert "NOT durable" in caplog.text
        assert "DATABASE_URL" in message
    else:
        assert message is None
        assert "NOT durable" not in caplog.text


def test_startup_warning_is_logged_at_import_without_crashing(tmp_path):
    """A production-like process with no durable store warns once and starts."""

    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DATABASE_URL",
            "TEST_DATABASE_URL",
            "CALYX_EVIDENCE_FEEDBACK_ROOT",
            "APP_ENV",
            "ENVIRONMENT",
        }
    }
    env.update({"RENDER": "true", "PYTHONPATH": str(repo_root)})
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.evidence_feedback.routes as r; print(r.router.prefix)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "/api/evidence-feedback"
    assert "Evidence feedback is NOT durable" in completed.stderr


# --- control characters are bad input in both stores, never a 503 --------------

CONTROL_CHARACTERS = ["\x00", "\x01", "\x1b", "\x7f", "\x85"]


def _lexicon_submission(version, **overrides):
    return {
        "object_id": version["object_id"],
        "object_version_hash": version["version_hash"],
        "object_type": "lexicon",
        "page_context": "/lexicon/labellum",
        "feedback_class": "suggest_correction",
        "statement": "Petal is misspelled.",
        "proposed_replacement": "a modified petal",
        "defect_kind": "typo",
        **overrides,
    }


@pytest.mark.parametrize("char", CONTROL_CHARACTERS, ids=lambda c: f"U+{ord(c):04X}")
def test_register_rejects_control_characters_in_object_id(store, char):
    client = client_for(store)
    response = client.post(
        "/api/evidence-feedback/objects",
        json={"object_id": f"lexicon:lab{char}ellum", "object_type": "lexicon", "payload": {"d": 1}},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {"code": "OBJECT_ID_INVALID_CHARACTERS"}
    assert store.repository().list_object_versions("lexicon:labellum") == []


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("object_id", "lexicon:labellum\x00", "OBJECT_ID_INVALID_CHARACTERS"),
        ("object_id", "lexicon:\x1blabellum", "OBJECT_ID_INVALID_CHARACTERS"),
        ("statement", "Petal is\x00 misspelled.", "STATEMENT_INVALID_CHARACTERS"),
        ("statement", "Petal is\x07 misspelled.", "STATEMENT_INVALID_CHARACTERS"),
        ("page_context", "/lexicon/\x00labellum", "PAGE_CONTEXT_INVALID_CHARACTERS"),
        ("proposed_replacement", "a modified\x00 petal", "PROPOSED_REPLACEMENT_INVALID_CHARACTERS"),
        ("citation", "Dressler\x00 1993", "CITATION_INVALID_CHARACTERS"),
        ("defect_kind", "typo\x00", "DEFECT_KIND_INVALID_CHARACTERS"),
        ("severity", "high\x00", "SEVERITY_INVALID_CHARACTERS"),
        ("source_partner_id", "partner\x00", "SOURCE_PARTNER_ID_INVALID_CHARACTERS"),
    ],
)
def test_submit_rejects_control_characters_identically_in_both_stores(store, field, value, code):
    client = client_for(store)
    version = register_object(
        client, object_id="lexicon:labellum", object_type="lexicon", payload={"definition": "a modified petel"}
    )
    response = client.post("/api/evidence-feedback/cases", json=_lexicon_submission(version, **{field: value}))
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {"code": code}
    # Nothing was stored: the listing is empty in either store.
    assert store.repository().list_cases(status=None, object_type=None, limit=10, before=None) == []


def test_submit_keeps_ordinary_line_structure_and_unicode(store):
    client = client_for(store)
    version = register_object(
        client, object_id="lexicon:labellum", object_type="lexicon", payload={"definition": "a modified petel"}
    )
    statement = "Line one.\n\tIndented line two.\r\nDracula × hybrid, 'petal' — see Dressler."
    response = client.post("/api/evidence-feedback/cases", json=_lexicon_submission(version, statement=statement))
    assert response.status_code == 201, response.text
    assert response.json()["case"]["statement"] == statement.strip()


@pytest.mark.parametrize("path", ["efc-%00abc", "efc-%1Babc", "efc-%7Fabc"])
def test_case_id_with_control_characters_is_422_not_503(store, path):
    client = client_for(store)
    status = client.get(f"/api/evidence-feedback/cases/{path}")
    assert status.status_code == 422, status.text
    assert status.json()["detail"] == {"code": "CASE_ID_INVALID_CHARACTERS"}
    trivial = client.post(
        f"/api/evidence-feedback/cases/{path}/accept-trivial", json={"corrected_payload": {"d": 2}}
    )
    assert trivial.status_code == 422, trivial.text
    assert trivial.json()["detail"] == {"code": "CASE_ID_INVALID_CHARACTERS"}
