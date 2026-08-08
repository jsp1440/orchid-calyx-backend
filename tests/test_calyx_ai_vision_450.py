from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ai_vision_governed as api
from app.security import verify_owner_or_api_key
from runtime.ai_vision_governed import GovernedVisionService
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _analysis(image_id: str = "flower-1", source_url: str = "https://example.org/flower.jpg") -> dict:
    return {
        "image": {
            "image_id": image_id,
            "sha256": _sha(image_id),
            "source_url": source_url,
            "license": "CC BY 4.0",
            "creator": "Fixture Photographer",
            "attribution": "Fixture Photographer / Example",
            "acquired_at": "2026-08-07T21:00:00Z",
        },
        "model": {
            "provider": "fixture-provider",
            "model_name": "orchid-vision-fixture",
            "model_version": "1.0",
            "inference_id": f"inference-{image_id}",
        },
        "prompt": {
            "prompt_id": "orchid-character-analysis",
            "prompt_version": "1.0",
            "prompt_sha256": _sha("prompt-v1"),
        },
        "taxon_resolution": {"state": "unresolved", "candidate_ids": []},
        "detected_parts": [
            {"part": "flower", "confidence": 0.93},
            {"part": "labellum", "confidence": 0.88},
        ],
        "character_observations": [
            {
                "character_id": "lip_color",
                "state": "purple",
                "confidence": 0.91,
                "provenance": [image_id, "region:labellum"],
            },
            {
                "character_id": "pseudobulb_shape",
                "state": "club-shaped",
                "confidence": 0.70,
                "provenance": [image_id, "whole-plant-context"],
            },
        ],
    }


def _registry(root: Path) -> None:
    create_registry_version(
        registry_id="vision-cattleya",
        version="2026-08",
        title="AI.Vision Matrix fixture",
        scope={"family": "Orchidaceae"},
        characters=[
            RegistryCharacter("lip_color", "Lip color", weight=2.0),
            RegistryCharacter("pseudobulb_shape", "Pseudobulb shape", weight=1.0),
        ],
        candidates=[
            Candidate(
                taxon_id="taxon:cattleya-labiata",
                scientific_name="Cattleya labiata",
                states={"lip_color": "purple", "pseudobulb_shape": "club-shaped"},
                provenance={"source": "reviewed-fixture"},
            ),
            Candidate(
                taxon_id="taxon:cattleya-warneri",
                scientific_name="Cattleya warneri",
                states={"lip_color": "magenta", "pseudobulb_shape": "fusiform"},
                provenance={"source": "reviewed-fixture"},
            ),
        ],
        provenance={"source": "reviewed-literature-fixture"},
        actor="test-reviewer",
        root=root,
    )


def test_flower_analysis_preserves_identity_rights_model_prompt_and_uncertainty(tmp_path: Path):
    service = GovernedVisionService(tmp_path / "vision")
    result = service.submit_analysis(_analysis())
    record = result["analysis"]
    assert result["created"] is True
    assert len(record["image"]["sha256"]) == 64
    assert record["image"]["license"] == "cc-by-4.0"
    assert record["image"]["attribution"].startswith("Fixture Photographer")
    assert record["model"]["model_name"] == "orchid-vision-fixture"
    assert len(record["prompt"]["prompt_sha256"]) == 64
    assert record["detected_parts"][0]["part"] == "flower"
    assert record["character_observations"][0]["confidence"] == 0.91
    assert record["review_state"] == "human_review_required"
    assert record["autonomous_species_identification"] is False


def test_unlicensed_and_unsupported_confidence_fail_closed(tmp_path: Path):
    service = GovernedVisionService(tmp_path / "vision")
    unlicensed = _analysis()
    unlicensed["image"]["license"] = "all rights reserved"
    try:
        service.submit_analysis(unlicensed)
    except ValueError as exc:
        assert "VISION_LICENSE_NOT_ALLOWED" in str(exc)
    else:
        raise AssertionError("unlicensed image must fail")

    overconfident = _analysis("flower-2", "https://example.org/flower2.jpg")
    overconfident["character_observations"][0]["confidence"] = 0.99
    try:
        service.submit_analysis(overconfident)
    except ValueError as exc:
        assert "UNSUPPORTED_VISION_CONFIDENCE" in str(exc)
    else:
        raise AssertionError("unsupported vision confidence must fail")


def test_human_correction_is_auditable_and_drives_matrix_handoff(tmp_path: Path):
    registry_root = tmp_path / "registry"
    session_root = tmp_path / "sessions"
    _registry(registry_root)
    service = GovernedVisionService(tmp_path / "vision")
    result = service.submit_analysis(_analysis())
    analysis_id = result["analysis"]["analysis_id"]

    corrected = service.correct_observation(
        analysis_id,
        character_id="lip_color",
        corrected_state="purple",
        reviewer="orchid-reviewer",
        rationale="Verified against flower image.",
        reviewed_at="2026-08-07T21:05:00Z",
    )
    assert corrected["corrections"][0]["reviewer"] == "orchid-reviewer"
    assert corrected["review_state"] == "corrected_review_required"

    handoff = service.matrix_handoff(
        analysis_id,
        registry_id="vision-cattleya",
        version="2026-08",
        registry_root=registry_root,
        session_root=session_root,
    )
    ranked = handoff["matrix_session"]["session"]["candidates"]
    assert ranked[0]["taxon_id"] == "taxon:cattleya-labiata"
    assert handoff["human_review_required"] is True
    assert handoff["autonomous_species_identification"] is False


def test_flower_and_tag_pair_are_distinct_evidence_artifacts(tmp_path: Path):
    service = GovernedVisionService(tmp_path / "vision")
    flower = service.submit_analysis(_analysis("flower-image", "https://example.org/flower.jpg"))["analysis"]
    tag_payload = _analysis("tag-image", "https://example.org/tag.jpg")
    tag_payload["detected_parts"] = [{"part": "plant_tag", "confidence": 0.90}]
    tag_payload["character_observations"] = []
    tag = service.submit_analysis(tag_payload)["analysis"]
    assert flower["analysis_id"] != tag["analysis_id"]
    assert flower["image"]["sha256"] != tag["image"]["sha256"]
    assert tag["detected_parts"][0]["part"] == "plant_tag"
    assert flower["artifact_id"] != tag["artifact_id"]


def test_matched_taxon_requires_canonical_id(tmp_path: Path):
    service = GovernedVisionService(tmp_path / "vision")
    payload = _analysis()
    payload["taxon_resolution"] = {"state": "matched"}
    try:
        service.submit_analysis(payload)
    except ValueError as exc:
        assert "VISION_MATCHED_TAXON_ID_REQUIRED" in str(exc)
    else:
        raise AssertionError("matched taxon without ID must fail")


def test_protected_status_and_correction_api(tmp_path: Path, monkeypatch):
    service = GovernedVisionService(tmp_path / "vision")
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    created = client.post("/brain/mission-control/vision/analyses", json=_analysis())
    assert created.status_code == 200
    analysis_id = created.json()["analysis"]["analysis_id"]
    status = client.get(f"/brain/mission-control/vision/analyses/{analysis_id}")
    assert status.status_code == 200
    assert status.json()["scientific_publication_authorized"] is False

    corrected = client.post(
        f"/brain/mission-control/vision/analyses/{analysis_id}/corrections",
        json={
            "character_id": "lip_color",
            "corrected_state": "purple",
            "reviewer": "reviewer",
            "rationale": "manual review",
            "reviewed_at": "2026-08-07T21:10:00Z",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["corrections"]
