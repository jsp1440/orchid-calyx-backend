from __future__ import annotations

from app.multimodal_intelligence.contracts import (
    CharacterDefinition,
    CharacterObservation,
    EvidenceSpan,
    ImageAnalysisResult,
    LiteratureClaim,
    MatrixProfile,
    ModelProvenance,
    PlantPartDetection,
    SourceIdentity,
)
from app.multimodal_intelligence.operator import MultimodalOperatorService


def _analysis() -> ImageAnalysisResult:
    return ImageAnalysisResult(
        image_id="img-1",
        content_hash="a" * 64,
        license_code="CC-BY-4.0",
        attribution="Fixture",
        model=ModelProvenance("fixture", "orchid", "1", "run-1"),
        detected_parts=(PlantPartDetection("flower", 0.9),),
        character_observations=(
            CharacterObservation("lip_shape", "lobed", 0.8, ("vision",)),
        ),
    )


def _definitions() -> dict[str, CharacterDefinition]:
    return {"lip_shape": CharacterDefinition("lip_shape", "Lip shape", ("lobed", "entire"))}


def _profiles() -> tuple[MatrixProfile, ...]:
    return (
        MatrixProfile("t1", "Orchis alpha", {"lip_shape": frozenset({"lobed"})}, ("matrix:v1",)),
        MatrixProfile("t2", "Orchis beta", {"lip_shape": frozenset({"entire"})}, ("matrix:v1",)),
    )


def _ambiguous_profiles() -> tuple[MatrixProfile, ...]:
    return (
        MatrixProfile("t1", "Orchis alpha", {"lip_shape": frozenset({"lobed"})}, ("matrix:v1",)),
        MatrixProfile("t2", "Orchis beta", {"lip_shape": frozenset({"lobed"})}, ("matrix:v1",)),
    )


def test_literature_validation_is_idempotent_and_review_gated() -> None:
    service = MultimodalOperatorService()
    claim = LiteratureClaim(
        claim_id="c1",
        source=SourceIdentity("s1", "Paper", "b" * 64),
        evidence_spans=(EvidenceSpan(0, 8, "evidence"),),
        predicate="has_character",
        object_value="lobed lip",
        confidence=0.8,
    )
    first = service.validate_literature_claim(claim)
    second = service.validate_literature_claim(claim)
    assert first.operation_id == second.operation_id
    assert first.result["publication_allowed"] is False
    assert service.review_queue()["total"] == 1


def test_matrix_and_vision_operator_paths_preserve_explanations() -> None:
    service = MultimodalOperatorService()
    vision = service.convert_vision(_analysis())
    assert vision.result["license_verified"] is True
    ranked = service.rank_matrix(
        definitions=_definitions(),
        observations=(CharacterObservation("lip_shape", "lobed", 0.8, ("manual",)),),
        profiles=_profiles(),
    )
    assert ranked.result["candidates"][0]["accepted_name"] == "Orchis alpha"
    assert ranked.result["candidates"][0]["contributions"]


def test_integrated_identification_and_abstention() -> None:
    service = MultimodalOperatorService()
    record = service.integrated_identification(
        analysis=_analysis(),
        definitions=_definitions(),
        profiles=_profiles(),
        minimum_margin=0.1,
    )
    assert record.result["abstained"] is False
    cautious = service.integrated_identification(
        analysis=_analysis(),
        definitions=_definitions(),
        profiles=_ambiguous_profiles(),
        minimum_margin=0.1,
    )
    assert cautious.result["abstained"] is True


def test_batch_plan_does_not_execute_and_rejects_unknown_types() -> None:
    service = MultimodalOperatorService()
    result = service.batch(
        (
            ("vision_conversion", {"image_id": "x"}),
            ("delete_database", {}),
        )
    )
    assert result["execution_enabled"] is False
    assert len(result["accepted"]) == 1
    assert result["rejected"][0]["reason"] == "UNSUPPORTED_OPERATION"


def test_audit_export_and_benchmark_are_deterministic() -> None:
    service = MultimodalOperatorService()
    assert service.export_audit()["record_count"] == 0
    benchmark = service.benchmark()
    assert benchmark["live_provider_calls"] == 0
    assert any(case["case_id"] == "identification-abstention" for case in benchmark["cases"])
