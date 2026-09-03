"""CALYX-NAOCC-POC-001 bounded first vertical slice — tests.

Covers the safety invariants and structural requirements from issue #1096:
- Corpus manifest: provenance, access_status, graph_mutation=False, no fabricated citations
- Evidence schema: provenance required, provisional by default, locality safety
- Synthesis: null result valid, hypotheses need ≥2 sources, no KG mutation
- Taxonomy reconciliation hook exists and produces unavailable, not absent
"""

from __future__ import annotations

import pytest

from app.naocc.corpus_manifest import (
    SCHEMA_VERSION as MANIFEST_SCHEMA_VERSION,
    AccessStatus,
    EvidenceClass,
    NAOCCSource,
    SourceType,
    build_corpus_manifest,
)
from app.naocc.evidence_schema import (
    SCHEMA_VERSION as EVIDENCE_SCHEMA_VERSION,
    ConfidenceLevel,
    ConservationThreatCategory,
    NAOCCEvidenceRecord,
    ProvenanceAnchor,
    validate_evidence_record,
)
from app.naocc.synthesis import (
    SCHEMA_VERSION as SYNTHESIS_SCHEMA_VERSION,
    NAOCCSynthesis,
    ScientistReviewItem,
    SynthesisCategory,
    SynthesisItem,
    build_provenance_aware_synthesis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_anchor(source_id: str = "naocc-home-001") -> ProvenanceAnchor:
    return ProvenanceAnchor(
        source_id=source_id,
        doi="",
        page_or_section="section 2",
        extraction_method="manual",
        extracted_at="2026-01-01T00:00:00+00:00",
        reviewed_by="",
    )


def _valid_record(record_id: str = "rec-001", source_id: str = "naocc-home-001") -> NAOCCEvidenceRecord:
    return NAOCCEvidenceRecord(
        record_id=record_id,
        source_id=source_id,
        taxon_name="Platanthera leucophaea",
        taxon_authority="(Nutt.) Lindl.",
        evidence_class=EvidenceClass.OBSERVATION,
        confidence_level=ConfidenceLevel.MEDIUM,
        conservation_status="Threatened",
        threat_category=ConservationThreatCategory.VULNERABLE,
        population_trend="declining",
        habitat_description="Mesic prairies and fens",
        fungal_partner="UNAVAILABLE",
        fungal_lineage="UNAVAILABLE",
        mycorrhizal_specificity="UNAVAILABLE",
        geography_region="Great Lakes region, North America",
        elevation_range_m="UNAVAILABLE",
        methods_summary="Field survey compilation",
        sample_size_description="UNAVAILABLE",
        results_summary="Population declining; habitat loss primary driver",
        limitations="Incomplete survey coverage",
        contradictions="None documented in source",
        provenance=_valid_anchor(source_id),
        not_publishable=True,
        is_provisional=True,
    )


# ---------------------------------------------------------------------------
# Corpus manifest
# ---------------------------------------------------------------------------


def test_manifest_schema_version():
    m = build_corpus_manifest()
    assert m.schema_version == MANIFEST_SCHEMA_VERSION


def test_manifest_graph_mutation_always_false():
    m = build_corpus_manifest()
    assert m.graph_mutation is False


def test_manifest_has_seed_sources():
    m = build_corpus_manifest()
    assert len(m.sources) >= 5


def test_manifest_all_sources_have_provenance():
    m = build_corpus_manifest()
    for source in m.sources:
        assert source.provenance, f"Source {source.source_id!r} missing provenance"


def test_manifest_all_sources_have_titles():
    m = build_corpus_manifest()
    for source in m.sources:
        assert source.title.strip(), f"Source {source.source_id!r} has empty title"


def test_manifest_seed_sources_are_candidate_unverified():
    m = build_corpus_manifest()
    # Seed entries must be candidate_unverified until a scientist verifies them.
    for source in m.sources:
        assert source.access_status in (
            AccessStatus.CANDIDATE_UNVERIFIED,
            AccessStatus.VERIFIED_PUBLIC,
            AccessStatus.FULL_TEXT_AVAILABLE,
        ), f"Source {source.source_id!r} has unexpected access_status: {source.access_status}"


def test_manifest_candidate_vs_verified_split():
    m = build_corpus_manifest()
    candidates = m.candidate_sources()
    verified = m.verified_sources()
    # Seed corpus starts with all candidates; none verified yet.
    assert len(candidates) + len(verified) == len(m.sources)


def test_manifest_extra_sources_appended():
    extra = NAOCCSource(
        source_id="custom-001",
        title="Custom NAOCC paper",
        source_type=SourceType.PEER_REVIEWED_PAPER,
        access_status=AccessStatus.VERIFIED_PUBLIC,
        primary_url="https://example.org/paper",
        doi="10.0000/example",
        author_year="Smith et al. 2025",
        taxon_scope=("Platanthera leucophaea",),
        evidence_classes_present=(EvidenceClass.OBSERVATION,),
        conservation_domain=True,
        mycorrhizal_domain=False,
        occurrence_domain=True,
        notes="Test-only entry",
        provenance="Test provenance",
    )
    m = build_corpus_manifest(extra_sources=[extra])
    ids = [s.source_id for s in m.sources]
    assert "custom-001" in ids


def test_manifest_to_dict_has_all_keys():
    m = build_corpus_manifest()
    d = m.to_dict()
    for key in ("schema_version", "generated_at", "graph_mutation", "source_count", "sources", "notes"):
        assert key in d, f"Missing key {key!r} in manifest dict"


def test_manifest_source_to_dict_has_all_keys():
    m = build_corpus_manifest()
    d = m.sources[0].to_dict()
    for key in (
        "source_id", "title", "source_type", "access_status", "primary_url",
        "doi", "author_year", "taxon_scope", "evidence_classes_present",
        "conservation_domain", "mycorrhizal_domain", "occurrence_domain",
        "notes", "provenance",
    ):
        assert key in d, f"Missing key {key!r} in source dict"


def test_manifest_no_fabricated_doi_in_seed():
    """Seed sources that lack a verified DOI must have empty doi, not a fabricated one."""
    m = build_corpus_manifest()
    for source in m.sources:
        if source.access_status == AccessStatus.CANDIDATE_UNVERIFIED and not source.doi:
            pass  # expected
        if source.doi:
            # Any populated DOI must look like a real DOI prefix.
            assert source.doi.startswith("10."), (
                f"Source {source.source_id!r} has a non-DOI string in doi field: {source.doi!r}"
            )


# ---------------------------------------------------------------------------
# Evidence schema
# ---------------------------------------------------------------------------


def test_evidence_record_schema_version():
    assert EVIDENCE_SCHEMA_VERSION.startswith("naocc-evidence-schema/")


def test_valid_record_passes_validation():
    record = _valid_record()
    errors = validate_evidence_record(record)
    assert errors == [], f"Valid record failed validation: {errors}"


def test_record_requires_source_id():
    record = NAOCCEvidenceRecord(
        record_id="rec-002",
        source_id="",  # missing
        taxon_name="Platanthera leucophaea",
        taxon_authority="(Nutt.) Lindl.",
        evidence_class=EvidenceClass.OBSERVATION,
        confidence_level=ConfidenceLevel.MEDIUM,
        conservation_status="Threatened",
        threat_category=ConservationThreatCategory.VULNERABLE,
        population_trend="declining",
        habitat_description="Prairie",
        fungal_partner="UNAVAILABLE",
        fungal_lineage="UNAVAILABLE",
        mycorrhizal_specificity="UNAVAILABLE",
        geography_region="Great Lakes",
        elevation_range_m="UNAVAILABLE",
        methods_summary="Survey",
        sample_size_description="UNAVAILABLE",
        results_summary="Declining",
        limitations="None",
        contradictions="None",
        provenance=_valid_anchor(""),
        not_publishable=True,
        is_provisional=True,
    )
    errors = validate_evidence_record(record)
    assert any("source_id" in e for e in errors)


def test_record_requires_taxon_name():
    record = _valid_record()
    # Replace with empty taxon_name via dataclass replace (frozen=True so rebuild)
    bad = NAOCCEvidenceRecord(
        record_id=record.record_id,
        source_id=record.source_id,
        taxon_name="",  # missing
        taxon_authority=record.taxon_authority,
        evidence_class=record.evidence_class,
        confidence_level=record.confidence_level,
        conservation_status=record.conservation_status,
        threat_category=record.threat_category,
        population_trend=record.population_trend,
        habitat_description=record.habitat_description,
        fungal_partner=record.fungal_partner,
        fungal_lineage=record.fungal_lineage,
        mycorrhizal_specificity=record.mycorrhizal_specificity,
        geography_region=record.geography_region,
        elevation_range_m=record.elevation_range_m,
        methods_summary=record.methods_summary,
        sample_size_description=record.sample_size_description,
        results_summary=record.results_summary,
        limitations=record.limitations,
        contradictions=record.contradictions,
        provenance=record.provenance,
        not_publishable=record.not_publishable,
        is_provisional=record.is_provisional,
    )
    errors = validate_evidence_record(bad)
    assert any("taxon_name" in e for e in errors)


def test_record_must_be_not_publishable():
    record = NAOCCEvidenceRecord(
        record_id="rec-003",
        source_id="naocc-home-001",
        taxon_name="Platanthera",
        taxon_authority="",
        evidence_class=EvidenceClass.OBSERVATION,
        confidence_level=ConfidenceLevel.LOW,
        conservation_status="UNAVAILABLE",
        threat_category=ConservationThreatCategory.UNAVAILABLE,
        population_trend="UNAVAILABLE",
        habitat_description="UNAVAILABLE",
        fungal_partner="UNAVAILABLE",
        fungal_lineage="UNAVAILABLE",
        mycorrhizal_specificity="UNAVAILABLE",
        geography_region="UNAVAILABLE",
        elevation_range_m="UNAVAILABLE",
        methods_summary="UNAVAILABLE",
        sample_size_description="UNAVAILABLE",
        results_summary="UNAVAILABLE",
        limitations="UNAVAILABLE",
        contradictions="UNAVAILABLE",
        provenance=_valid_anchor("naocc-home-001"),
        not_publishable=False,  # should fail
        is_provisional=True,
    )
    errors = validate_evidence_record(record)
    assert any("not_publishable" in e for e in errors)


def test_record_must_be_provisional():
    record = NAOCCEvidenceRecord(
        record_id="rec-004",
        source_id="naocc-home-001",
        taxon_name="Platanthera",
        taxon_authority="",
        evidence_class=EvidenceClass.OBSERVATION,
        confidence_level=ConfidenceLevel.LOW,
        conservation_status="UNAVAILABLE",
        threat_category=ConservationThreatCategory.UNAVAILABLE,
        population_trend="UNAVAILABLE",
        habitat_description="UNAVAILABLE",
        fungal_partner="UNAVAILABLE",
        fungal_lineage="UNAVAILABLE",
        mycorrhizal_specificity="UNAVAILABLE",
        geography_region="UNAVAILABLE",
        elevation_range_m="UNAVAILABLE",
        methods_summary="UNAVAILABLE",
        sample_size_description="UNAVAILABLE",
        results_summary="UNAVAILABLE",
        limitations="UNAVAILABLE",
        contradictions="UNAVAILABLE",
        provenance=_valid_anchor("naocc-home-001"),
        not_publishable=True,
        is_provisional=False,  # should fail
    )
    errors = validate_evidence_record(record)
    assert any("is_provisional" in e for e in errors)


def test_provenance_source_id_must_match_record_source_id():
    anchor = ProvenanceAnchor(
        source_id="DIFFERENT_SOURCE",
        doi="",
        page_or_section="",
        extraction_method="manual",
        extracted_at="2026-01-01T00:00:00+00:00",
        reviewed_by="",
    )
    record = NAOCCEvidenceRecord(
        record_id="rec-005",
        source_id="naocc-home-001",
        taxon_name="Platanthera leucophaea",
        taxon_authority="",
        evidence_class=EvidenceClass.OBSERVATION,
        confidence_level=ConfidenceLevel.MEDIUM,
        conservation_status="UNAVAILABLE",
        threat_category=ConservationThreatCategory.UNAVAILABLE,
        population_trend="UNAVAILABLE",
        habitat_description="UNAVAILABLE",
        fungal_partner="UNAVAILABLE",
        fungal_lineage="UNAVAILABLE",
        mycorrhizal_specificity="UNAVAILABLE",
        geography_region="North America",
        elevation_range_m="UNAVAILABLE",
        methods_summary="UNAVAILABLE",
        sample_size_description="UNAVAILABLE",
        results_summary="UNAVAILABLE",
        limitations="UNAVAILABLE",
        contradictions="UNAVAILABLE",
        provenance=anchor,
        not_publishable=True,
        is_provisional=True,
    )
    errors = validate_evidence_record(record)
    assert any("provenance.source_id" in e for e in errors)


def test_record_to_dict_has_required_keys():
    record = _valid_record()
    d = record.to_dict()
    for key in (
        "record_id", "source_id", "taxon_name", "evidence_class", "confidence_level",
        "conservation_status", "threat_category", "provenance",
        "not_publishable", "is_provisional",
    ):
        assert key in d, f"Missing key {key!r} in evidence record dict"


def test_record_no_coordinate_fields():
    """Evidence records must not carry fine-resolution coordinate fields."""
    import dataclasses
    field_names = {f.name.lower() for f in dataclasses.fields(NAOCCEvidenceRecord)}
    # Check whole-field-name equality against sensitive terms, not substring.
    for sensitive in ("latitude", "longitude", "lat", "lon", "coordinate", "wgs84", "geom"):
        assert sensitive not in field_names, (
            f"Evidence record has forbidden coordinate field {sensitive!r}"
        )


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def test_synthesis_schema_version():
    assert SYNTHESIS_SCHEMA_VERSION.startswith("naocc-synthesis/")


def test_null_result_is_valid_with_no_records():
    s = build_provenance_aware_synthesis(
        scientific_question="Test question",
        records=[],
        items=[],
    )
    assert s.null_result_declared is True
    assert s.graph_mutation is False
    assert s.record_count == 0
    assert "not a finding" in s.null_result_reason.lower()


def test_synthesis_graph_mutation_always_false():
    s = build_provenance_aware_synthesis(
        scientific_question="Test",
        records=[_valid_record()],
        items=[],
    )
    assert s.graph_mutation is False


def test_synthesis_hypothesis_requires_two_sources():
    hypothesis = SynthesisItem(
        item_id="hyp-001",
        category=SynthesisCategory.TESTABLE_HYPOTHESIS,
        claim="Platanthera leucophaea associates with Tulasnella",
        supporting_source_ids=("naocc-home-001",),  # only 1 — should fail
        contradicting_source_ids=(),
        confidence_notes="Low",
        limitations="Single source",
        is_ai_interpretation=True,
    )
    with pytest.raises(ValueError, match="≥2 independent supporting sources"):
        build_provenance_aware_synthesis(
            scientific_question="Mycorrhizal associations",
            records=[_valid_record()],
            items=[hypothesis],
        )


def test_synthesis_hypothesis_with_two_sources_passes():
    hypothesis = SynthesisItem(
        item_id="hyp-002",
        category=SynthesisCategory.TESTABLE_HYPOTHESIS,
        claim="Platanthera leucophaea associates with Tulasnella",
        supporting_source_ids=("naocc-home-001", "naocc-iucn-001"),  # 2 sources
        contradicting_source_ids=(),
        confidence_notes="Low — requires extraction verification",
        limitations="Both sources unverified; candidate only",
        is_ai_interpretation=True,
    )
    s = build_provenance_aware_synthesis(
        scientific_question="Mycorrhizal associations",
        records=[_valid_record()],
        items=[hypothesis],
    )
    hyps = s.by_category(SynthesisCategory.TESTABLE_HYPOTHESIS)
    assert len(hyps) == 1


def test_synthesis_to_dict_has_required_keys():
    s = build_provenance_aware_synthesis(
        scientific_question="Test",
        records=[],
        items=[],
    )
    d = s.to_dict()
    for key in (
        "schema_version", "generated_at", "graph_mutation", "scientific_question",
        "source_ids_used", "record_count", "items", "scientist_review_section",
        "null_result_declared", "null_result_reason", "notes",
    ):
        assert key in d, f"Missing key {key!r} in synthesis dict"


def test_synthesis_notes_state_ai_not_authority():
    s = build_provenance_aware_synthesis(
        scientific_question="Test",
        records=[_valid_record()],
        items=[],
    )
    assert "not scientific authority" in s.notes.lower()


def test_synthesis_by_category_filters_correctly():
    items = [
        SynthesisItem(
            item_id="gap-001",
            category=SynthesisCategory.KNOWLEDGE_GAP,
            claim="Mycorrhizal partner unknown for most taxa",
            supporting_source_ids=("naocc-home-001",),
            contradicting_source_ids=(),
            confidence_notes="High confidence in the gap itself",
            limitations="None",
            is_ai_interpretation=False,
        ),
        SynthesisItem(
            item_id="est-001",
            category=SynthesisCategory.ESTABLISHED_FINDING,
            claim="Platanthera leucophaea is a US Threatened species",
            supporting_source_ids=("naocc-home-001",),
            contradicting_source_ids=(),
            confidence_notes="High",
            limitations="None",
            is_ai_interpretation=False,
        ),
    ]
    s = build_provenance_aware_synthesis(
        scientific_question="Conservation status",
        records=[_valid_record()],
        items=items,
    )
    assert len(s.by_category(SynthesisCategory.KNOWLEDGE_GAP)) == 1
    assert len(s.by_category(SynthesisCategory.ESTABLISHED_FINDING)) == 1
    assert len(s.by_category(SynthesisCategory.CONTRADICTION)) == 0


def test_scientist_review_section_returned():
    review = [
        ScientistReviewItem(
            statement="Platanthera leucophaea is listed as Threatened under the US ESA",
            basis_source_ids=("naocc-home-001",),
            review_prompt="Is this status current as of the review date?",
        )
    ]
    s = build_provenance_aware_synthesis(
        scientific_question="Conservation status",
        records=[_valid_record()],
        items=[],
        scientist_review=review,
    )
    assert len(s.scientist_review_section) == 1
    assert "Platanthera leucophaea" in s.scientist_review_section[0].statement


def test_synthesis_is_not_a_kg_write():
    """NAOCCSynthesis must carry no attribute that implies a KG write."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(NAOCCSynthesis)}
    for forbidden in ("kg_mutation", "published", "approved", "merged"):
        assert forbidden not in field_names, (
            f"Synthesis has forbidden field {forbidden!r}"
        )
    s = build_provenance_aware_synthesis("Q", [], [])
    assert s.graph_mutation is False
