from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.canonical_brain.api import create_brain_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_brain_router(), prefix="/brain")
    return TestClient(app)


def test_status_exposes_constitution_version() -> None:
    response = _client().get("/brain/canonical/status")
    assert response.status_code == 200
    assert response.json()["constitution_version"] == "1.0.0"


def test_admission_endpoint_is_non_mutating_and_blocks_merge_authority() -> None:
    client = _client()
    before = client.get("/brain/canonical/status").json()["snapshot_checksum"]
    response = client.post(
        "/brain/canonical/admission/evaluate",
        json={
            "build_id": "build:api-test",
            "architecture_id": "architecture:brain",
            "intent_ids": ["intent:enable-governed-autonomy"],
            "decision_ids": ["decision:brain"],
            "source_uris": ["docs/architecture/BUILD-BRAIN-105-CONSTITUTION.md"],
            "validation_plan_ids": ["validation:brain-105"],
            "deterministic_outputs": True,
            "preserves_provenance": True,
            "separates_evidence_from_inference": True,
            "merge_requested": True,
        },
    )
    after = client.get("/brain/canonical/status").json()["snapshot_checksum"]

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert before == after
