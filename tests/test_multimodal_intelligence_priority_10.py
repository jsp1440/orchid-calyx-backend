from __future__ import annotations

import pytest

from app.multimodal_intelligence.contracts import (
    CharacterDefinition,
    CharacterObservation,
    ImageAnalysisResult,
    MatrixProfile,
    ModelProvenance,
    PlantPartDetection,
)
from app.multimodal_intelligence.integration import (
    DisabledOCRAdapter,
    DocumentPage,
    DocumentRecord,
    FixtureVisionProvider,
    MatrixDataset,
    MatrixRegistry,
    TaxonomyResolver,
    candidate_knowledge_payload,
    extract_label_tokens,
    filter_profiles,
    identify_from_image,
    literature_claim_from_phrase,
)


def _dataset() -> MatrixDataset:
    definitions = {
        "lip_shape": CharacterDefinition("lip_shape", "Lip shape", ("entire", "lobed"), 1.0),
        "spur": CharacterDefinition("spur", "Spur", ("present", "absent"), 1.2),
    }
    profiles = (
        MatrixProfile(
            taxon_id="taxon:anceps",
            accepted_name="Laelia anceps",
            states={"lip_shape": frozenset({"lobed"}), "spur": frozenset({"absent"})},
            provenance=("literature:1",),
        ),
        MatrixProfile(
            taxon_id="taxon:autumnalis",
            accepted_name="Laelia autumnalis",
            states={"lip_shape": frozenset({"entire"}), "spur": frozenset({"absent"})},
            provenance=("literature:2",),
        ),
    )
    return MatrixDataset(
        matrix_id="laelia-demo",
        version="1.0.0",
        definitions=definitions,
        profiles=profiles,
        geography={
            "taxon:anceps": frozenset({"Mexico", "California cultivation"}),
            "taxon:autumnalis": frozenset({"Mexico"}),
        },
        flowering_months={
            "taxon:anceps": frozenset({11, 12, 1}),
            "taxon:autumnalis": frozenset({9, 10, 11}),
        },
    )


def _vision_result() -> ImageAnalysisResult:
    return ImageAnalysisResult(
        image_id="img-1",
        content_hash="a" * 64,
        license_code="CC-BY-4.0",
        attribution="Fixture photographer",
        model=ModelProvenance("fixture", "orchid-parts", "1", "run-1"),
        detected_parts=(PlantPartDetection("flower", 0.94), PlantPartDetection("lip", 0.91)),
        character_observations=(
            CharacterObservation("lip_shape", "lobed", 0.90, ("vision:lip",)),
            CharacterObservation("spur", "absent", 0.80, ("vision:spur",)),
        ),
    )


def test_document_adapter_hash_and_literature_claim() -> None:
    document = DocumentRecord(
        source_id="paper:1",
        title="A Laelia study",
        pages=(DocumentPage(1, "Laelia anceps has a lobed lip."),),
    )
    resolver = TaxonomyResolver(
        accepted={"Laelia anceps": "taxon:anceps"},
        synonyms={"Cattleya anceps": "Laelia anceps"},
    )
    claim = literature_claim_from_phrase(
        document=document,
        page_number=1,
        phrase="lobed lip",
        predicate="has_character_state",
        object_value="lip_shape=lobed",
        taxon_name="Cattleya anceps",
        resolver=resolver,
        confidence=0.92,
    )
    assert len(document.content_hash) == 64
    assert claim.canonical_taxon_id == "taxon:anceps"
    payload = candidate_knowledge_payload(claim)
    assert payload["publication_state"] == "human_review_required"
    assert payload["source"]["content_hash"] == document.content_hash


def test_document_adapter_rejects_missing_evidence_phrase() -> None:
    document = DocumentRecord("paper:1", "Study", (DocumentPage(1, "text"),))
    with pytest.raises(ValueError, match="EVIDENCE_PHRASE_NOT_FOUND"):
        literature_claim_from_phrase(
            document=document,
            page_number=1,
            phrase="missing",
            predicate="p",
            object_value="o",
        )


def test_disabled_ocr_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="OCR_PROVIDER_NOT_CONFIGURED"):
        DisabledOCRAdapter().extract(image_id="scan-1", image_bytes=b"data")


def test_taxonomy_resolver_accepts_names_synonyms_and_unresolved() -> None:
    resolver = TaxonomyResolver(
        accepted={"Laelia anceps": "taxon:anceps"},
        synonyms={"Cattleya anceps": "Laelia anceps"},
    )
    assert resolver.resolve("Laelia anceps").status == "accepted"
    assert resolver.resolve("Cattleya anceps").status == "synonym"
    assert resolver.resolve("Unknown orchid").status == "unresolved"


def test_matrix_registry_is_versioned_and_replay_safe() -> None:
    registry = MatrixRegistry()
    dataset = _dataset()
    registry.register(dataset)
    assert registry.get("laelia-demo", "1.0.0") is dataset
    with pytest.raises(ValueError, match="MATRIX_VERSION_ALREADY_EXISTS"):
        registry.register(dataset)


def test_geography_and_phenology_filters() -> None:
    dataset = _dataset()
    assert [profile.taxon_id for profile in filter_profiles(dataset, region="California cultivation")] == [
        "taxon:anceps"
    ]
    assert [profile.taxon_id for profile in filter_profiles(dataset, flowering_month=10)] == [
        "taxon:autumnalis"
    ]


def test_fixture_vision_provider_and_integrated_identification() -> None:
    result = _vision_result()
    identification = identify_from_image(
        provider=FixtureVisionProvider(result),
        image_id=result.image_id,
        content_hash=result.content_hash,
        dataset=_dataset(),
        region="California cultivation",
        flowering_month=12,
        label_text="L. anceps 2026-014",
    )
    assert identification.abstained is False
    assert identification.candidates[0].taxon_id == "taxon:anceps"
    assert "anceps" in identification.label_tokens
    assert "2026" in identification.label_tokens


def test_identification_abstains_when_candidates_are_too_close() -> None:
    result = _vision_result()
    identification = identify_from_image(
        provider=FixtureVisionProvider(result),
        image_id=result.image_id,
        content_hash=result.content_hash,
        dataset=_dataset(),
        minimum_margin=1.0,
    )
    assert identification.abstained is True
    assert identification.abstention_reason == "CANDIDATE_MARGIN_TOO_SMALL"


def test_label_token_extraction_is_deterministic() -> None:
    assert extract_label_tokens("Laelia anceps 'Snow' 2026-014") == (
        "Laelia",
        "anceps",
        "Snow",
        "2026",
        "014",
    )
