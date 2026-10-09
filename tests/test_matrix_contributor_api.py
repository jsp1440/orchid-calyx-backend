"""API-level tests for the authenticated Matrix contributor intake router.

Exercises the real HTTP surface through FastAPI's ASGI stack: authentication,
batch intake, filename→session mapping, suggestion listing, the review gate,
scoring connection, idempotent replay, and cross-owner fail-closed behavior.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.matrix_contributor import router as contributor_router
from app.security import create_owner_session_token
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)

API_KEY = "test-contributor-key"
OWNER_SECRET = "test-owner-session-secret"
PHOTO_A = b"\xff\xd8\xff\xe0" + b"orchid-photo-alpha" * 8
PHOTO_B = b"\x89PNG\r\n\x1a\n" + b"orchid-photo-beta" * 8


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _env(tmp_path: Path) -> None:
    os.environ["CALYX_API_KEY"] = API_KEY
    os.environ["CALYX_OWNER_SESSION_SECRET"] = OWNER_SECRET
    os.environ["CALYX_MATRIX_SESSION_DIR"] = str(tmp_path / "sessions")
    os.environ["CALYX_MATRIX_REGISTRY_DIR"] = str(tmp_path / "registries")
    os.environ["CALYX_MATRIX_CONTRIBUTOR_INTAKE_DIR"] = str(tmp_path / "intake")
    os.environ.pop("CALYX_MATRIX_SESSION_DURABLE_ENABLED", None)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(contributor_router)
    return TestClient(app)


def _make_registry() -> None:
    create_registry_version(
        registry_id="phragmipedium-demo",
        version="1",
        title="Phragmipedium bounded diagnostic matrix",
        scope={"genus": "Phragmipedium"},
        characters=[
            RegistryCharacter("petal_color", "Petal color", weight=1),
            RegistryCharacter("pouch_shape", "Pouch shape", weight=2),
        ],
        candidates=[
            Candidate(
                "world-plants:phragmipedium-besseae",
                "Phragmipedium besseae",
                {"petal_color": "red", "pouch_shape": "slipper"},
                provenance={"source": "test"},
            ),
            Candidate(
                "world-plants:phragmipedium-kovachii",
                "Phragmipedium kovachii",
                {"petal_color": "pink", "pouch_shape": "slipper"},
                provenance={"source": "test"},
            ),
        ],
        provenance={"source": "test"},
        actor="test",
    )


def _intake_payload() -> dict:
    return {
        "batch_id": "api-batch-1",
        "open_sessions": True,
        "registry_id": "phragmipedium-demo",
        "registry_version": "1",
        "submissions": [
            {
                "original_filename": "kovachii_flower.jpg",
                "content_base64": _b64(PHOTO_A),
                "contributor_display_name": "R. Orchidist",
                "permission_grant": "cc-by-nc",
                "rights_holder_affirmed": True,
                "taxon_certainty": "unknown",
                "candidate_taxa": [{"name": "Phragmipedium kovachii"}],
            },
            {
                "original_filename": "unknown_garden.png",
                "content_base64": _b64(PHOTO_B),
                "contributor_display_name": "S. Gardener",
                "permission_grant": "cc-by",
                "rights_holder_affirmed": True,
                "taxon_certainty": "unknown",
            },
        ],
    }


def _intake(client: TestClient, **overrides) -> dict:
    payload = _intake_payload()
    payload.update(overrides)
    response = client.post(
        "/api/matrix-contributor/intake",
        json=payload,
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_intake_requires_authentication(tmp_path) -> None:
    _env(tmp_path)
    client = _client()
    assert client.post("/api/matrix-contributor/intake", json=_intake_payload()).status_code == 401
    assert (
        client.post(
            "/api/matrix-contributor/intake",
            json=_intake_payload(),
            headers={"X-API-Key": "wrong"},
        ).status_code
        == 401
    )
    assert client.get("/api/matrix-contributor/batches/anything").status_code == 401


def test_intake_maps_filenames_to_sessions_and_persists_manifest(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    client = _client()
    manifest = _intake(client)
    assert manifest["summary"]["staged_count"] == 2
    assert manifest["sessions_opened"] == 2
    mapping = {item["original_filename"]: item for item in manifest["filename_mapping"]}
    first = mapping["kovachii_flower.jpg"]
    assert first["status"] == "staged"
    assert first["session"]["registry_id"] == "phragmipedium-demo"
    assert first["attribution_line"] == "R. Orchidist (CC-BY-NC)"
    assert first["permission_grant"] == "cc-by-nc"
    stored = client.get(
        "/api/matrix-contributor/batches/api-batch-1",
        headers={"X-API-Key": API_KEY},
    )
    assert stored.status_code == 200
    assert stored.json()["batch_id"] == "api-batch-1"
    original_ref = first["original_object_ref"]
    assert (tmp_path / "intake" / original_ref).read_bytes() == PHOTO_A


def test_intake_replay_is_idempotent_across_restart(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    first = _intake(_client())
    # Simulate a process restart: a brand-new app over the same governed roots.
    replayed = _intake(_client())
    assert replayed["idempotent_replay"] is True
    assert (
        replayed["filename_mapping"][0]["session"]["session_id"]
        == first["filename_mapping"][0]["session"]["session_id"]
    )
    session_files = list((tmp_path / "sessions").glob("*.json"))
    assert len(session_files) == 2


def test_review_gate_controls_scoring_through_api(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    client = _client()
    manifest = _intake(client)
    entry = manifest["filename_mapping"][0]
    session_id = entry["session"]["session_id"]
    submission_id = entry["submission_id"]
    headers = {"X-API-Key": API_KEY}

    attached = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/extractions",
        json={
            "submission_id": submission_id,
            "extractions": [
                {
                    "character": "petal_color",
                    "value": "pink",
                    "machine_confidence": 0.81,
                    "extractor": "vision-stub",
                    "extractor_version": "0.1.0",
                }
            ],
        },
        headers=headers,
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["suggestions"][0]["state"] == "pending_review"

    before = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/evaluate",
        json={"limit": 5},
        headers=headers,
    )
    assert before.status_code == 200
    assert before.json()["report"]["observation_count"] == 0

    suggestions = client.get(
        f"/api/matrix-contributor/sessions/{session_id}/suggestions",
        headers=headers,
    )
    assert suggestions.status_code == 200
    suggestion_id = suggestions.json()["suggestions"][0]["suggestion_id"]

    reviewed = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/suggestions/{suggestion_id}/review",
        json={"decision": "accept", "certainty": "probable"},
        headers=headers,
    )
    assert reviewed.status_code == 200, reviewed.text

    after = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/evaluate",
        json={"limit": 5},
        headers=headers,
    )
    assert after.status_code == 200
    assert after.json()["report"]["observation_count"] == 1
    candidates = {
        item["scientific_name"]: item for item in after.json()["report"]["candidates"]
    }
    assert (
        candidates["Phragmipedium kovachii"]["score"]
        > candidates["Phragmipedium besseae"]["score"]
    )

    record = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/evidence-record",
        json={"submission_id": submission_id},
        headers=headers,
    )
    assert record.status_code == 200, record.text
    body = record.json()
    assert body["verification_status"] == "unverified_candidate_evidence"
    assert body["contributor_image"]["content_sha256"] == entry["content_sha256"]
    assert body["reviewed_observations"][0]["source"]["kind"] == "contributor_image_reviewed"

    second_review = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/suggestions/{suggestion_id}/review",
        json={"decision": "reject"},
        headers=headers,
    )
    assert second_review.status_code == 422


def test_owner_sessions_are_tenant_scoped_and_fail_closed(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    client = _client()
    token_a = create_owner_session_token("owner-a")["token"]
    token_b = create_owner_session_token("owner-b")["token"]

    response = client.post(
        "/api/matrix-contributor/intake",
        json=_intake_payload(),
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 200, response.text
    entry = response.json()["filename_mapping"][0]
    session_id = entry["session"]["session_id"]

    owner_read = client.get(
        f"/api/matrix-contributor/sessions/{session_id}/suggestions",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert owner_read.status_code == 200

    cross_owner = client.get(
        f"/api/matrix-contributor/sessions/{session_id}/suggestions",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_owner.status_code == 404

    cross_owner_review = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/suggestions/whatever/review",
        json={"decision": "accept", "certainty": "certain"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_owner_review.status_code == 404

    # Owner identity cannot be spoofed through submission fields.
    staged = response.json()["staged"][0]
    assert staged["contributor_id"] == "owner-a"
