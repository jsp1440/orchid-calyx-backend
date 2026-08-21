from __future__ import annotations

from app.scientific_synthesis.claim_verification import verify_claim
from app.scientific_synthesis.models import (
    ArticleDraft,
    ArticleSentence,
    BibliographicRecord,
    ClaimKind,
    EvidenceAnchor,
    EvidenceClass,
    EvidenceMatrixRow,
    SynthesisClaim,
    VerificationState,
)
from app.scientific_synthesis.routes import health
from app.scientific_synthesis.service import ScientificSynthesisService


def _source(source_id: str = "paper-1") -> BibliographicRecord:
    return BibliographicRecord(
        source_id=source_id,
        title="Thermal niche and dormancy in Phalaenopsis",
        authors=("A. Researcher",),
        year=2026,
        journal="Orchid Science",
        doi="10.0000/example",
        verification_state=VerificationState.VERIFIED_PUBLISHER,
        verification_provider="Crossref",
        verification_identifier="10.0000/example",
    )


def _row(
    evidence_id: str,
    *,
    evidence_class: EvidenceClass = EvidenceClass.OBSERVATIONAL,
    result: str = "Seasonal dormancy covaries with cooler montane occurrence records.",
    metadata: dict | None = None,
) -> EvidenceMatrixRow:
    return EvidenceMatrixRow(
        evidence_id=evidence_id,
        source_id="paper-1",
        evidence_class=evidence_class,
        anchors=(
            EvidenceAnchor(
                anchor_id=f"anchor-{evidence_id}",
                source_id="paper-1",
                source_revision_id="paper-1-r1",
                locator={"page": 7, "section": "Results", "char_start": 1200, "char_end": 1310},
                content_hash="a" * 64,
                excerpt_hash="b" * 64,
            ),
        ),
        taxon="Phalaenopsis",
        method="comparative occurrence and trait analysis",
        result=result,
        uncertainty="phylogenetic clustering remains a confounder",
        limitations=("not phylogenetically controlled",),
        metadata={
            "authorized_excerpt": "Seasonal dormancy was associated with cooler montane taxa.",
            "occurrence_ids": [101, 102, 103],
            "analysis_recipe": {
                "operation": "compare_groups",
                "predictor": "seasonal_dormancy",
                "outcome": "thermal_niche",
            },
            **(metadata or {}),
        },
    )


def _article(claim_id: str) -> ArticleDraft:
    return ArticleDraft(
        article_id="answer-1",
        title="Calyx answer",
        sentences=(
            ArticleSentence(
                sentence_id="sentence-1",
                text="Seasonal dormancy is associated with cooler thermal niches.",
                scientific=True,
                claim_ids=(claim_id,),
            ),
        ),
        audience="researcher",
        format="calyx_answer",
        bibliography_source_ids=("paper-1",),
    )


def _manifest(claim: SynthesisClaim, rows: tuple[EvidenceMatrixRow, ...]):
    service = ScientificSynthesisService()
    return service.validate(
        bibliography=(_source(),),
        evidence_rows=rows,
        claims=(claim,),
        article=_article(claim.claim_id),
    )


def test_check_calyx_returns_auditable_argument_and_exact_source_bundle():
    row = _row("ev-1")
    claim = SynthesisClaim(
        claim_id="claim-1",
        text="Seasonal dormancy is associated with cooler thermal niches in the current Phalaenopsis evidence.",
        kind=ClaimKind.SYNTHESIS,
        supporting_evidence_ids=(row.evidence_id,),
    )
    result = verify_claim(
        claim_id=claim.claim_id,
        bibliography=(_source(),),
        evidence_rows=(row,),
        claims=(claim,),
        validation_manifest=_manifest(claim, (row,)),
    )

    assert result["operation"] == "CHECK_CALYX"
    assert result["verdict"] == "well_supported_synthesis"
    assert result["verification_status"] == "verified"
    assert result["scientific_argument"]["argument_type"] == "externally_auditable_scientific_argument"
    assert result["scientific_argument"]["private_chain_of_thought_included"] is False

    evidence = result["evidence_bundle"]["supporting"][0]
    assert evidence["source"]["verification_state"] == "VERIFIED_PUBLISHER"
    assert evidence["anchors"][0]["locator"]["page"] == 7
    assert evidence["anchors"][0]["source_revision_id"] == "paper-1-r1"
    assert evidence["display_excerpt"].startswith("Seasonal dormancy")
    assert evidence["occurrence_ids"] == [101, 102, 103]
    assert evidence["analysis_recipe"]["outcome"] == "thermal_niche"
    assert result["reproducibility"]["rerunnable_evidence_ids"] == ["ev-1"]
    assert len(result["reproducibility"]["verification_fingerprint"]) == 64


def test_check_calyx_preserves_counterevidence_and_marks_claim_contested():
    support = _row("support")
    conflict = _row(
        "conflict",
        result="Some warm-growing exposed-canopy species also have thick leaves, so leaf thickness is not uniquely diagnostic.",
    )
    claim = SynthesisClaim(
        claim_id="claim-contested",
        text="Leaf thickness distinguishes cool-growing Phalaenopsis.",
        kind=ClaimKind.SYNTHESIS,
        supporting_evidence_ids=(support.evidence_id,),
        conflicting_evidence_ids=(conflict.evidence_id,),
    )
    rows = (support, conflict)
    result = verify_claim(
        claim_id=claim.claim_id,
        bibliography=(_source(),),
        evidence_rows=rows,
        claims=(claim,),
        validation_manifest=_manifest(claim, rows),
    )

    assert result["verdict"] == "contested"
    assert result["evidence_bundle"]["conflicting"][0]["evidence_id"] == "conflict"
    assert any(
        step["step"] == "counterevidence"
        for step in result["scientific_argument"]["steps"]
    )


def test_check_calyx_requires_explicit_inference_rationale():
    row = _row("ev-inference")
    claim = SynthesisClaim(
        claim_id="claim-inference",
        text="Seasonal dormancy evolved as an adaptation to cool dry winters.",
        kind=ClaimKind.INFERENCE,
        supporting_evidence_ids=(row.evidence_id,),
        inference_rationale=None,
    )
    manifest = _manifest(claim, (row,))
    result = verify_claim(
        claim_id=claim.claim_id,
        bibliography=(_source(),),
        evidence_rows=(row,),
        claims=(claim,),
        validation_manifest=manifest,
    )

    assert result["verdict"] == "claim_exceeds_evidence"
    rationale_check = next(
        check for check in result["checks"] if check["check_id"] == "inference_rationale"
    )
    assert rationale_check["status"] == "fail"
    assert result["verification_status"] == "failed"


def test_check_calyx_health_advertises_verification_without_private_cot():
    status = health()
    assert status["check_calyx"] is True
    assert status["auditable_scientific_argument"] is True
    assert status["private_chain_of_thought_exposed"] is False
    assert status["publishes_knowledge"] is False
