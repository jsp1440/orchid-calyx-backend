from app.multimodal_intelligence import (
    CharacterDefinition,
    CharacterObservation,
    EvidenceSpan,
    ImageAnalysisResult,
    LiteratureClaim,
    MatrixProfile,
    ModelProvenance,
    PlantPartDetection,
    SourceIdentity,
    matrix_observations_from_vision,
    rank_matrix_candidates,
)


def test_literature_claim_requires_provenance_and_span() -> None:
    claim = LiteratureClaim(
        claim_id="claim-1",
        source=SourceIdentity("doi:1", "Orchid paper", "a" * 64),
        evidence_spans=(EvidenceSpan(0, 12, "lip trilobed"),),
        predicate="lip_shape",
        object_value="trilobed",
        canonical_taxon_id="taxon:1",
        confidence=0.88,
    )
    claim.validate()


def test_vision_observations_feed_matrix_with_model_provenance() -> None:
    result = ImageAnalysisResult(
        image_id="image-1",
        content_hash="b" * 64,
        license_code="CC-BY-4.0",
        attribution="Example Photographer",
        model=ModelProvenance("fixture", "orchid-parts", "1", "run-1"),
        detected_parts=(PlantPartDetection("flower", 0.94),),
        character_observations=(
            CharacterObservation("lip_shape", "trilobed", 0.91, ("vision",)),
        ),
    )
    observations = matrix_observations_from_vision(result)
    assert observations[0].confidence == 0.91
    assert "image:image-1" in observations[0].provenance


def test_matrix_ranking_is_explainable_and_missing_data_safe() -> None:
    definitions = {
        "lip_shape": CharacterDefinition("lip_shape", "Lip shape", ("entire", "trilobed"), 2.0),
        "growth_habit": CharacterDefinition("growth_habit", "Growth habit", ("epiphytic", "terrestrial")),
    }
    observations = (
        CharacterObservation("lip_shape", "trilobed", 0.9, ("image:image-1",)),
        CharacterObservation("growth_habit", None, 0.5, ("operator:unknown",)),
    )
    profiles = (
        MatrixProfile("taxon:1", "Example orchid A", {"lip_shape": frozenset({"trilobed"})}, ("literature:1",)),
        MatrixProfile("taxon:2", "Example orchid B", {"lip_shape": frozenset({"entire"})}, ("literature:2",)),
    )
    ranked = rank_matrix_candidates(definitions=definitions, observations=observations, profiles=profiles)
    assert ranked[0].taxon_id == "taxon:1"
    assert ranked[0].support_count == 1
    assert ranked[0].unknown_count == 1
    assert ranked[1].contradiction_count == 1
    assert ranked[0].contributions[0].outcome == "support"
