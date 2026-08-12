from fastapi import HTTPException
import pytest

import app.routers.matrix_identification_registry as registry_router

CONCEPT_A = "11111111-1111-4111-8111-111111111111"


def _payload():
    return registry_router.RegistryConceptMappingDerivationRequest(
        new_version="2",
        mappings=[
            registry_router.RegistryConceptMappingInput(
                character="spur_length_mm",
                concept_id=CONCEPT_A,
            )
        ],
        review_note="Reviewed against canonical morphology concept.",
    )


def test_mapping_api_requires_active_approved_concept_and_uses_authenticated_reviewer(monkeypatch):
    monkeypatch.setattr(
        registry_router,
        "_load_entry_by_concept_id",
        lambda concept_id: {
            "concept_id": str(concept_id),
            "preferred_term": "spur",
            "source_system": "oc_concepts",
            "source_record_id": str(concept_id),
            "review_state": "approved",
        },
    )
    captured = {}

    def fake_derive(**kwargs):
        captured.update(kwargs)
        return {
            "created": True,
            "record": {
                "registry_id": kwargs["registry_id"],
                "version": kwargs["new_version"],
                "checksum_sha256": "checksum",
                "publication_state": "review_required",
            },
        }

    monkeypatch.setattr(
        registry_router,
        "derive_registry_version_with_concept_mappings",
        fake_derive,
    )

    result = registry_router.derive_concept_mappings(
        "angraecum",
        "1",
        _payload(),
        {"auth_type": "session", "actor": "reviewer@example.org"},
    )

    assert captured["actor"] == "reviewer@example.org"
    assert captured["concept_mappings"] == {"spur_length_mm": CONCEPT_A}
    assert captured["mapping_provenance"]["approved_concepts"][0]["preferred_term"] == "spur"
    assert result["automatic_concept_matching"] is False
    assert result["automatic_publication"] is False


def test_mapping_api_rejects_concept_that_is_not_active_and_approved(monkeypatch):
    monkeypatch.setattr(registry_router, "_load_entry_by_concept_id", lambda concept_id: None)

    with pytest.raises(HTTPException) as raised:
        registry_router.derive_concept_mappings(
            "angraecum",
            "1",
            _payload(),
            {"auth_type": "session", "actor": "reviewer@example.org"},
        )

    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "MATRIX_CONCEPT_MAPPING_NOT_APPROVED"


def test_mapping_api_rejects_duplicate_character_decisions(monkeypatch):
    payload = registry_router.RegistryConceptMappingDerivationRequest(
        new_version="2",
        mappings=[
            registry_router.RegistryConceptMappingInput(character="spur_length_mm", concept_id=CONCEPT_A),
            registry_router.RegistryConceptMappingInput(character="spur_length_mm", concept_id=CONCEPT_A),
        ],
    )

    with pytest.raises(HTTPException) as raised:
        registry_router.derive_concept_mappings(
            "angraecum",
            "1",
            payload,
            {"auth_type": "session", "actor": "reviewer@example.org"},
        )

    assert raised.value.status_code == 422
    assert "duplicate concept mapping" in str(raised.value.detail)
