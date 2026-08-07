from app.multimodal_intelligence.contracts import (
    EvidenceSpan,
    LiteratureClaim,
    SourceIdentity,
)
from app.multimodal_intelligence.operator import MultimodalOperatorService
from app.multimodal_intelligence.promotion import (
    build_candidate_knowledge_promotion_plan,
    require_eligible_promotion,
)


def _claim() -> LiteratureClaim:
    return LiteratureClaim(
        claim_id="claim-1",
        source=SourceIdentity(
            source_id="paper-1",
            title="Test paper",
            content_hash="a" * 64,
        ),
        evidence_spans=(EvidenceSpan(start=0, end=12, text="orchid trait"),),
        predicate="has_trait",
        object_value="pendant inflorescence",
        canonical_taxon_id="taxon-1",
        confidence=0.82,
    )


def test_promotion_requires_human_approval() -> None:
    service = MultimodalOperatorService()
    record = service.validate_literature_claim(_claim())
    plan = build_candidate_knowledge_promotion_plan(record)
    assert plan.eligible is False
    assert "HUMAN_REVIEW_APPROVAL_REQUIRED" in plan.blockers
    assert plan.automatic_execution is False


def test_approved_literature_operation_yields_nonexecuting_promotion_plan() -> None:
    service = MultimodalOperatorService()
    record = service.validate_literature_claim(_claim())
    approved = service.decide_review(
        record.operation_id,
        decision="approve",
        rationale="Evidence and provenance verified.",
        reviewer="owner",
    )
    plan = require_eligible_promotion(build_candidate_knowledge_promotion_plan(approved))
    assert plan.eligible is True
    assert plan.target == "candidate_knowledge"
    assert plan.payload["published"] is False
    assert plan.payload["review_required"] is True
    assert plan.automatic_execution is False


def test_nonliterature_operation_cannot_promote_to_candidate_knowledge() -> None:
    service = MultimodalOperatorService()
    record = service._record("matrix_ranking", {"x": 1}, {"candidate_count": 0})
    approved = service.decide_review(
        record.operation_id,
        decision="approve",
        rationale="Ranking reviewed.",
        reviewer="owner",
    )
    plan = build_candidate_knowledge_promotion_plan(approved)
    assert plan.eligible is False
    assert "LITERATURE_OPERATION_REQUIRED" in plan.blockers
