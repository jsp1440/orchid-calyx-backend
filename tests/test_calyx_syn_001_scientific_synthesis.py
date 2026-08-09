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
from app.scientific_synthesis.service import ScientificSynthesisService


def source(*, verified=True):
    return BibliographicRecord(
        source_id="doi:10.1000/orchid.1",
        title="Orchid foliar nitrogen uptake",
        authors=("A. Researcher",),
        year=2026,
        journal="Journal of Orchid Science",
        doi="10.1000/orchid.1",
        verification_state=(
            VerificationState.VERIFIED_PUBLISHER if verified else VerificationState.UNVERIFIED
        ),
        verification_provider="publisher" if verified else None,
        verification_identifier="10.1000/orchid.1" if verified else None,
    )


def evidence(*, evidence_class=EvidenceClass.DIRECT_TRACER):
    return EvidenceMatrixRow(
        evidence_id="ev-1",
        source_id="doi:10.1000/orchid.1",
        evidence_class=evidence_class,
        anchors=(
            EvidenceAnchor(
                anchor_id="anchor-1",
                source_id="doi:10.1000/orchid.1",
                source_revision_id="revision-1",
                locator={"page": 4, "section": "Results", "start": 120, "end": 180},
                content_hash="source-sha256",
                excerpt_hash="excerpt-sha256",
            ),
        ),
        taxon="Phalaenopsis",
        intervention="foliar 15N",
        comparator="root 15N",
        outcome="nitrogen uptake",
        method="isotope tracer",
        result="label detected after foliar application",
    )


def claim(*, kind=ClaimKind.DIRECT):
    return SynthesisClaim(
        claim_id="claim-1",
        text="The orchid leaf absorbed applied nitrogen.",
        kind=kind,
        supporting_evidence_ids=("ev-1",),
        inference_rationale=("Mechanistic interpretation" if kind is ClaimKind.INFERENCE else None),
    )


def article(*, grounded=True):
    return ArticleDraft(
        article_id="article-1",
        title="Can Orchids Really Foliar Feed?",
        sentences=(
            ArticleSentence(
                sentence_id="sentence-1",
                text="The orchid leaf absorbed applied nitrogen.",
                scientific=True,
                claim_ids=(("claim-1",) if grounded else ()),
            ),
        ),
        audience="orchid society newsletter",
        format="newsletter_article",
        bibliography_source_ids=("doi:10.1000/orchid.1",),
    )


def validate(*, bibliography=None, evidence_rows=None, claims=None, draft=None):
    return ScientificSynthesisService().validate(
        bibliography=tuple(bibliography or [source()]),
        evidence_rows=tuple(evidence_rows or [evidence()]),
        claims=tuple(claims or [claim()]),
        article=draft or article(),
    )


def codes(result):
    return {item["code"] for item in result["errors"]}


def test_verified_primary_evidence_can_ground_scientific_article():
    result = validate()

    assert result["publication_ready"] is True
    assert result["state"] == "SYNTHESIS_VALIDATED"
    assert result["verified_source_count"] == 1
    assert result["primary_experimental_evidence_count"] == 1


def test_unverified_primary_source_blocks_publication():
    result = validate(bibliography=[source(verified=False)])

    assert result["publication_ready"] is False
    assert "PRIMARY_EVIDENCE_SOURCE_UNVERIFIED" in codes(result)
    assert "ARTICLE_BIBLIOGRAPHY_SOURCE_UNVERIFIED" in codes(result)


def test_scientific_sentence_without_claim_link_is_blocked():
    result = validate(draft=article(grounded=False))

    assert result["publication_ready"] is False
    assert "SCIENTIFIC_SENTENCE_UNGROUNDED" in codes(result)


def test_direct_claim_cannot_be_supported_only_by_vendor_or_practice_claim():
    result = validate(evidence_rows=[evidence(evidence_class=EvidenceClass.COMMERCIAL_CLAIM)])

    assert result["publication_ready"] is False
    assert "DIRECT_CLAIM_REQUIRES_PRIMARY_EXPERIMENTAL_EVIDENCE" in codes(result)
    assert any(
        item["code"] == "CLAIM_SUPPORTED_ONLY_BY_PRACTICE_OR_COMMERCIAL_EVIDENCE"
        for item in result["warnings"]
    )


def test_inference_requires_explicit_rationale():
    unsupported_inference = SynthesisClaim(
        claim_id="claim-1",
        text="Foliar uptake may be an adaptation to canopy nutrient pulses.",
        kind=ClaimKind.INFERENCE,
        supporting_evidence_ids=("ev-1",),
    )
    result = validate(claims=[unsupported_inference])

    assert result["publication_ready"] is False
    assert "INFERENCE_RATIONALE_REQUIRED" in codes(result)


def test_validation_fingerprint_is_deterministic():
    first = validate()
    second = validate()

    assert first["fingerprint"] == second["fingerprint"]
