from app.scientific_synthesis.models import (
    EvidenceAnchor,
    EvidenceClass,
    EvidenceMatrixRow,
)
from app.scientific_synthesis.pipeline import EvidenceClassificationDecision
from app.scientific_synthesis.pipeline_routes import _require_primary_class_review


def _row(evidence_class: EvidenceClass) -> EvidenceMatrixRow:
    return EvidenceMatrixRow(
        evidence_id="ev-1",
        source_id="source-1",
        evidence_class=evidence_class,
        anchors=(
            EvidenceAnchor(
                anchor_id="anchor-1",
                source_id="source-1",
                source_revision_id="revision-1",
                locator={"page": 1},
                content_hash="source-hash",
                excerpt_hash="excerpt-hash",
            ),
        ),
        outcome="leaf nutrient uptake",
        result="A source-bound result.",
    )


def _decision(evidence_class: EvidenceClass) -> EvidenceClassificationDecision:
    return EvidenceClassificationDecision(
        evidence_id="ev-1",
        evidence_class=evidence_class,
        reviewer_id="reviewer-1",
        rationale="Methods and results support this reviewed evidence class.",
    )


def test_primary_class_requires_matching_review_decision() -> None:
    row = _row(EvidenceClass.DIRECT_TRACER)
    try:
        _require_primary_class_review((row,), ())
    except ValueError as exc:
        assert str(exc) == "PRIMARY_EVIDENCE_CLASS_REVIEW_REQUIRED"
    else:
        raise AssertionError("unreviewed primary evidence class was accepted")


def test_primary_class_rejects_mismatched_review_class() -> None:
    row = _row(EvidenceClass.DIRECT_TRACER)
    try:
        _require_primary_class_review(
            (row,), (_decision(EvidenceClass.CONTROLLED_EXPERIMENT),)
        )
    except ValueError as exc:
        assert str(exc) == "PRIMARY_EVIDENCE_CLASS_REVIEW_REQUIRED"
    else:
        raise AssertionError("mismatched review class was accepted")


def test_primary_class_accepts_exact_reviewed_class() -> None:
    row = _row(EvidenceClass.DIRECT_TRACER)
    _require_primary_class_review((row,), (_decision(EvidenceClass.DIRECT_TRACER),))


def test_conservative_initial_class_does_not_require_review_decision() -> None:
    _require_primary_class_review((_row(EvidenceClass.OBSERVATIONAL),), ())
