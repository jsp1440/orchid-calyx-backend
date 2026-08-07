import pytest

from app.multimodal_intelligence.api_models import (
    IntegratedIdentificationRequest,
    LiteratureValidationRequest,
    MatrixRankingRequest,
    VisionAnalysisRequest,
)


def _vision_payload() -> dict:
    return {
        "image_id": "image-1",
        "content_hash": "b" * 64,
        "license_code": "CC-BY-4.0",
        "attribution": "Test photographer",
        "model": {
            "provider": "fixture",
            "model_name": "orchid-vision",
            "model_version": "1",
            "inference_id": "run-1",
        },
        "detected_parts": [{"part": "flower", "confidence": 0.9}],
        "character_observations": [
            {
                "character_id": "lip_shape",
                "state": "lobed",
                "confidence": 0.8,
                "provenance": ["fixture:image-1"],
            }
        ],
    }


def test_literature_request_builds_contract() -> None:
    request = LiteratureValidationRequest.model_validate(
        {
            "claim_id": "claim-1",
            "source": {
                "source_id": "paper-1",
                "title": "Paper",
                "content_hash": "a" * 64,
            },
            "evidence_spans": [{"start": 0, "end": 6, "text": "orchid"}],
            "predicate": "has_trait",
            "object_value": "lobed lip",
            "canonical_taxon_id": "taxon-1",
            "confidence": 0.8,
        }
    )
    claim = request.contract()
    claim.validate()
    assert claim.source.source_id == "paper-1"
    assert claim.evidence_spans[0].text == "orchid"


def test_matrix_request_rejects_duplicate_character_definitions() -> None:
    payload = {
        "definitions": [
            {"character_id": "lip", "label": "Lip", "allowed_states": ["lobed"]},
            {"character_id": "lip", "label": "Lip 2", "allowed_states": ["entire"]},
        ],
        "observations": [
            {
                "character_id": "lip",
                "state": "lobed",
                "confidence": 0.8,
                "provenance": ["fixture"],
            }
        ],
        "profiles": [
            {
                "taxon_id": "taxon-1",
                "accepted_name": "Orchis testii",
                "states": {"lip": ["lobed"]},
                "provenance": ["matrix:v1"],
            }
        ],
    }
    request = MatrixRankingRequest.model_validate(payload)
    with pytest.raises(ValueError, match="DUPLICATE_CHARACTER_DEFINITION"):
        request.contracts()


def test_vision_request_preserves_license_and_model_provenance() -> None:
    request = VisionAnalysisRequest.model_validate(_vision_payload())
    analysis = request.contract()
    analysis.validate()
    assert analysis.license_code == "CC-BY-4.0"
    assert analysis.model.provider == "fixture"


def test_integrated_identification_request_builds_all_contracts() -> None:
    request = IntegratedIdentificationRequest.model_validate(
        {
            "analysis": _vision_payload(),
            "definitions": [
                {"character_id": "lip_shape", "label": "Lip shape", "allowed_states": ["lobed", "entire"]}
            ],
            "profiles": [
                {
                    "taxon_id": "taxon-1",
                    "accepted_name": "Orchis testii",
                    "states": {"lip_shape": ["lobed"]},
                    "provenance": ["matrix:v1"],
                }
            ],
            "minimum_margin": 0.2,
        }
    )
    analysis, definitions, profiles, margin = request.contracts()
    assert analysis.image_id == "image-1"
    assert set(definitions) == {"lip_shape"}
    assert profiles[0].taxon_id == "taxon-1"
    assert margin == 0.2
