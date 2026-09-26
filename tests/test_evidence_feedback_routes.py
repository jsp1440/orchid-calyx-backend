from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.evidence_feedback.routes import router
from app.security import verify_owner_or_api_key


def client_for(tmp_path, monkeypatch, actor="member-1"):
    monkeypatch.setenv("CALYX_EVIDENCE_FEEDBACK_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": actor,
        "auth_type": "test",
    }
    return TestClient(app)


def register_object(client, *, object_id, object_type, payload):
    response = client.post(
        "/evidence-feedback/objects",
        json={
            "object_id": object_id,
            "object_type": object_type,
            "payload": payload,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_authenticated_lexicon_feedback_survives_new_client(
    tmp_path,
    monkeypatch,
):
    client = client_for(tmp_path, monkeypatch)
    version = register_object(
        client,
        object_id="lexicon:labellum",
        object_type="lexicon",
        payload={"definition": "a modified petel"},
    )

    submitted = client.post(
        "/evidence-feedback/cases",
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

    restarted = client_for(tmp_path, monkeypatch)
    status = restarted.get(f"/evidence-feedback/cases/{case['case_id']}")

    assert status.status_code == 200
    assert status.json()["case_id"] == case["case_id"]
    assert status.json()["status"] == "pending_review"


def test_duplicate_http_submission_is_suppressed(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
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

    first = client.post("/evidence-feedback/cases", json=request)
    second = client.post("/evidence-feedback/cases", json=request)

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["duplicate_of"] == first.json()["case"]["case_id"]


def test_submitter_cannot_read_another_identity_case(tmp_path, monkeypatch):
    owner = client_for(tmp_path, monkeypatch, actor="member-1")
    version = register_object(
        owner,
        object_id="matrix:episode:7",
        object_type="matrix_identification",
        payload={"candidates": ["taxon:1", "taxon:2"]},
    )
    submitted = owner.post(
        "/evidence-feedback/cases",
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

    other = client_for(tmp_path, monkeypatch, actor="member-2")
    response = other.get(f"/evidence-feedback/cases/{case_id}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CASE_STATUS_NOT_VISIBLE"


def test_scientific_case_cannot_use_trivial_correction_route(
    tmp_path,
    monkeypatch,
):
    client = client_for(tmp_path, monkeypatch)
    version = register_object(
        client,
        object_id="image:annotation:9",
        object_type="image_annotation",
        payload={"taxon_id": "taxon:1"},
    )
    submitted = client.post(
        "/evidence-feedback/cases",
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
        f"/evidence-feedback/cases/{case['case_id']}/accept-trivial",
        json={"corrected_payload": {"taxon_id": "taxon:2"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GOVERNED_REVIEW_REQUIRED"


def test_trivial_route_versions_instead_of_overwriting(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, actor="reviewer-1")
    original = register_object(
        client,
        object_id="lexicon:sepal",
        object_type="lexicon",
        payload={"definition": "outer floral whorl partt"},
    )
    submitted = client.post(
        "/evidence-feedback/cases",
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
        f"/evidence-feedback/cases/{case_id}/accept-trivial",
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
