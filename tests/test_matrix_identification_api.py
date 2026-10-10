"""API-level tests for the Phase 3 identification endpoint.

Exercises POST /api/matrix-contributor/sessions/{id}/identification over the
real ASGI stack: authentication boundary, owner tenant scoping, repeated-call
idempotency, and persistence across a simulated restart.
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

API_KEY = "test-identification-key"
OWNER_SECRET = "test-identification-owner-secret"
PHOTO = b"\xff\xd8\xff\xe0" + b"kovachii-flower-photo" * 8


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
        registry_id="phragmipedium-api",
        version="1",
        title="Phragmipedium api test matrix",
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


def _drive_reviewed_session(client: TestClient, headers: dict) -> str:
    intake = client.post(
        "/api/matrix-contributor/intake",
        json={
            "batch_id": "id-api-batch-1",
            "open_sessions": True,
            "registry_id": "phragmipedium-api",
            "registry_version": "1",
            "submissions": [
                {
                    "original_filename": "kovachii_flower.jpg",
                    "content_base64": _b64(PHOTO),
                    "contributor_display_name": "R. Orchidist",
                    "permission_grant": "cc-by-nc",
                    "rights_holder_affirmed": True,
                    "taxon_certainty": "unknown",
                }
            ],
        },
        headers=headers,
    )
    assert intake.status_code == 200, intake.text
    entry = intake.json()["filename_mapping"][0]
    session_id = entry["session"]["session_id"]
    submission_id = entry["submission_id"]

    attached = client.post(
        f"/api/matrix-contributor/sessions/{session_id}/extractions",
        json={
            "submission_id": submission_id,
            "extractions": [
                {"character": "petal_color", "value": "pink",
                 "machine_confidence": 0.81, "extractor": "vision-stub",
                 "extractor_version": "0.1.0"},
                {"character": "pouch_shape", "value": "slipper",
                 "machine_confidence": 0.66, "extractor": "vision-stub",
                 "extractor_version": "0.1.0"},
            ],
        },
        headers=headers,
    )
    assert attached.status_code == 200, attached.text
    for suggestion in attached.json()["suggestions"]:
        reviewed = client.post(
            f"/api/matrix-contributor/sessions/{session_id}"
            f"/suggestions/{suggestion['suggestion_id']}/review",
            json={"decision": "accept", "certainty": "probable"},
            headers=headers,
        )
        assert reviewed.status_code == 200, reviewed.text
    return session_id


def _identify(client: TestClient, session_id: str, headers: dict):
    return client.post(
        f"/api/matrix-contributor/sessions/{session_id}/identification",
        json={"limit": 5},
        headers=headers,
    )


def test_identification_requires_authentication(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    client = _client()
    response = client.post(
        "/api/matrix-contributor/sessions/whatever/identification", json={}
    )
    assert response.status_code == 401
    response = client.post(
        "/api/matrix-contributor/sessions/whatever/identification",
        json={},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


def test_identification_report_over_http_and_repeat_idempotency(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    client = _client()
    headers = {"X-API-Key": API_KEY}
    session_id = _drive_reviewed_session(client, headers)

    response = _identify(client, session_id, headers)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["schema_version"] == "matrix-identification-report/v1"
    assert report["observation_count"] == 2
    leader = report["ranked_candidates"][0]
    assert leader["scientific_name"] == "Phragmipedium kovachii"
    assert {row["character"] for row in leader["supporting_characters"]} == {
        "petal_color",
        "pouch_shape",
    }
    besseae = next(
        item
        for item in report["ranked_candidates"]
        if item["scientific_name"] == "Phragmipedium besseae"
    )
    assert {row["character"] for row in besseae["contradicting_characters"]} == {
        "petal_color"
    }
    link = leader["supporting_characters"][0]["evidence_links"][0]
    assert link["attribution_line"] == "R. Orchidist (CC-BY-NC)"
    assert report["review_gate"]["rule"]
    assert any(
        "not a taxonomic determination" in item for item in report["limitations"]
    )

    # Repeated requests return an identical scientific payload checksum.
    repeat = _identify(client, session_id, headers)
    assert repeat.status_code == 200
    assert repeat.json()["checksum_sha256"] == report["checksum_sha256"]


def test_identification_is_owner_scoped_and_fails_closed(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    client = _client()
    token_a = create_owner_session_token("owner-a")["token"]
    token_b = create_owner_session_token("owner-b")["token"]
    session_id = _drive_reviewed_session(
        client, {"Authorization": f"Bearer {token_a}"}
    )

    own = _identify(client, session_id, {"Authorization": f"Bearer {token_a}"})
    assert own.status_code == 200

    cross = _identify(client, session_id, {"Authorization": f"Bearer {token_b}"})
    assert cross.status_code == 404


def test_identification_report_persists_across_restart(tmp_path) -> None:
    _env(tmp_path)
    _make_registry()
    headers = {"X-API-Key": API_KEY}
    session_id = _drive_reviewed_session(_client(), headers)
    before = _identify(_client(), session_id, headers).json()

    # Simulated restart: a brand-new app instance over the same governed roots.
    restarted_client = _client()
    after = _identify(restarted_client, session_id, headers)
    assert after.status_code == 200
    assert after.json()["checksum_sha256"] == before["checksum_sha256"]
    assert after.json()["observation_count"] == 2
