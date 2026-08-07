from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.canonical_brain import build_canonical_brain_fixture, create_brain_router


def test_admission_endpoint_blocks_unsafe_build_without_mutating_brain() -> None:
    registry = build_canonical_brain_fixture()
    before = registry.snapshot().snapshot_checksum
    app = FastAPI()
    app.include_router(create_brain_router(registry))
    client = TestClient(app)
    response = client.post(
        "/brain/canonical/admission/evaluate",
        json={
            "build_id": "build:unsafe",
            "architecture_id": "architecture:brain",
            "intent_ids": ["intent:enable-governed-autonomy"],
            "decision_ids": ["decision:brain-canonical-memory"],
            "source_uris": ["test://unsafe"],
            "validation_plan_ids": ["validation:test"],
            "deterministic_outputs": True,
            "preserves_provenance": True,
            "separates_evidence_from_inference": True,
            "merge_requested": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert registry.snapshot().snapshot_checksum == before
