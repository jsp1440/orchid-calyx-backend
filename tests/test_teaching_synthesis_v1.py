"""Tests for CALYX-SYNTHESIS-001 TeachingSynthesisV1 contract.

Acceptance criteria from #1082:
- multi-domain synthesis is claim/relationship-first, not source-family-first;
- provenance survives from input to output;
- unknown/unavailable semantics survive (UNAVAILABLE ≠ biological absence);
- contradictions remain contradictions (not resolved into support);
- no locality leakage;
- no user/generated explanation enters the evidence set;
- canonical species identities are stable across rotation payloads.
"""

from __future__ import annotations

import pytest

from app.calyx_conversation.teaching_synthesis import (
    CONTRACT_VERSION,
    ORDERED_DOMAINS,
    SCHEMA_VERSION,
    AudienceLevel,
    DepthLevel,
    EvidenceState,
    RelationshipClaim,
    SubjectIdentity,
    TeachingSynthesisV1,
    _build_domain_relationship,
    _build_narrative_segment,
    build_featured_genus_pool,
    build_teaching_synthesis,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subject(name: str = "Laelia anceps") -> SubjectIdentity:
    return SubjectIdentity(
        taxon_name=name,
        taxon_id="taxon-001",
        common_names=("Laelia",),
        taxon_rank="species",
        canonical_source="hassler-2026-08",
        synonym_names=(),
        authority="Lindl.",
    )


def _claim(statement: str, domain: str = "habitat", conflict: bool = False) -> dict:
    return {
        "statement": statement,
        "source_references": [
            {"source": "test-source", "type": "peer_reviewed", "review_state": "CANONICAL"}
        ],
        "is_conflict": conflict,
    }


def _domain_data_with_claims(*statements: str, conflicts: list | None = None) -> dict:
    return {
        "claims": [_claim(s) for s in statements],
        "conflicts": [
            {"statement": c, "source_references": [{"source": "src-b", "type": "t", "review_state": "R"}]}
            for c in (conflicts or [])
        ],
    }


# ---------------------------------------------------------------------------
# SubjectIdentity
# ---------------------------------------------------------------------------


def test_subject_identity_round_trips():
    s = _subject()
    d = s.to_dict()
    assert d["taxon_name"] == "Laelia anceps"
    assert d["canonical_source"] == "hassler-2026-08"
    assert d["authority"] == "Lindl."


# ---------------------------------------------------------------------------
# RelationshipClaim — generated interpretation guard
# ---------------------------------------------------------------------------


def test_relationship_claim_rejects_generated_interpretation():
    with pytest.raises(ValueError, match="generated_interpretation"):
        RelationshipClaim(
            claim_id="test:0",
            domain="habitat",
            statement="This AI-generated claim",
            evidence_state=EvidenceState.SUPPORTED,
            source_references=(),
            is_generated_interpretation=True,
        )


def test_relationship_claim_allows_non_generated():
    c = RelationshipClaim(
        claim_id="test:0",
        domain="habitat",
        statement="Grows in cloud forests",
        evidence_state=EvidenceState.SUPPORTED,
        source_references=({"source": "s1"},),
        is_generated_interpretation=False,
    )
    assert c.is_generated_interpretation is False


# ---------------------------------------------------------------------------
# Domain assembly
# ---------------------------------------------------------------------------


def test_none_domain_data_yields_unavailable():
    rel = _build_domain_relationship("habitat", None)
    assert rel.evidence_state == EvidenceState.UNAVAILABLE
    assert "not a finding" in rel.unavailable_reason.lower() or "not queried" in rel.unavailable_reason.lower()


def test_empty_claims_yields_gap():
    rel = _build_domain_relationship("habitat", {"claims": [], "gaps": ["no records found"]})
    assert rel.evidence_state == EvidenceState.GAP
    assert len(rel.claims) == 0


def test_supported_claims_yield_supported_state():
    data = _domain_data_with_claims("Grows epiphytically at 1200–2000 m elevation.")
    rel = _build_domain_relationship("habitat", data)
    assert rel.evidence_state == EvidenceState.SUPPORTED
    assert len(rel.claims) == 1
    assert rel.claims[0].statement == "Grows epiphytically at 1200–2000 m elevation."


def test_conflicts_yield_conflict_state():
    data = _domain_data_with_claims(
        "Reports mycorrhizal association with Tulasnella.",
        conflicts=["Alternative study found no Tulasnella association."],
    )
    rel = _build_domain_relationship("mycorrhizae", data)
    assert rel.evidence_state == EvidenceState.CONFLICT
    conflict_claims = [c for c in rel.claims if c.evidence_state == EvidenceState.CONFLICT]
    assert len(conflict_claims) >= 1


def test_conflicts_not_resolved_into_support():
    """Contradictions must remain contradictions, never silently promoted to support."""
    data = _domain_data_with_claims(
        "Primary pollinator is Eulaema.",
        conflicts=["No Eulaema observed in field study."],
    )
    rel = _build_domain_relationship("pollination", data)
    assert rel.evidence_state == EvidenceState.CONFLICT
    # Conflict claims must preserve their conflict state.
    conflict_ids = [c.claim_id for c in rel.claims if c.evidence_state == EvidenceState.CONFLICT]
    assert conflict_ids, "Conflict claims must appear in output"


def test_provenance_survives_from_input_to_claims():
    data = {
        "claims": [
            {
                "statement": "Epiphytic on oak.",
                "source_references": [
                    {
                        "source": "doi:10.1234/test",
                        "type": "peer_reviewed",
                        "review_state": "CANONICAL",
                        "extra_field": "preserved",
                    }
                ],
            }
        ]
    }
    rel = _build_domain_relationship("habitat", data)
    assert len(rel.claims) == 1
    refs = rel.claims[0].source_references
    assert len(refs) == 1
    assert refs[0]["source"] == "doi:10.1234/test"
    assert refs[0]["type"] == "peer_reviewed"


def test_locality_fields_stripped_from_provenance():
    data = {
        "claims": [
            {
                "statement": "Found in Oaxaca.",
                "source_references": [
                    {
                        "source": "gbif-rec-1",
                        "type": "occurrence",
                        "review_state": "PUBLIC",
                        "latitude": "17.06",
                        "longitude": "-96.72",
                    }
                ],
            }
        ]
    }
    rel = _build_domain_relationship("geography", data)
    refs = rel.claims[0].source_references
    assert "latitude" not in refs[0]
    assert "longitude" not in refs[0]


# ---------------------------------------------------------------------------
# Narrative segments — claim-first, not source-family-first
# ---------------------------------------------------------------------------


def test_narrative_segment_unavailable_domain():
    rel = _build_domain_relationship("conservation", None)
    seg = _build_narrative_segment("conservation", rel)
    assert seg.evidence_state == EvidenceState.UNAVAILABLE
    assert "not available" in seg.text.lower() or "not" in seg.text.lower()


def test_narrative_segment_gap_domain():
    rel = _build_domain_relationship("conservation", {"claims": [], "gap_reason": "No IUCN listing."})
    seg = _build_narrative_segment("conservation", rel)
    assert seg.evidence_state == EvidenceState.GAP
    assert "gap" in seg.text.lower() or "no iucn" in seg.text.lower()


def test_narrative_segment_supported_starts_with_heading():
    data = _domain_data_with_claims("Pollinators include euglossine bees.")
    rel = _build_domain_relationship("pollination", data)
    seg = _build_narrative_segment("pollination", rel)
    assert seg.evidence_state == EvidenceState.SUPPORTED
    assert "Pollination" in seg.heading


def test_narrative_segments_are_claim_first_not_source_family_first():
    """The narrative must not list sources, then claims under each source."""
    data = _domain_data_with_claims(
        "Claim A about mycorrhiza.",
        "Claim B about mycorrhiza.",
    )
    rel = _build_domain_relationship("mycorrhizae", data)
    seg = _build_narrative_segment("mycorrhizae", rel)
    # Claim text must appear in segment, not a source-family header like "Knowledge Graph:"
    assert "Claim A" in seg.text or "Claim B" in seg.text
    assert "knowledge_graph" not in seg.text.lower()


# ---------------------------------------------------------------------------
# Full synthesis build
# ---------------------------------------------------------------------------


def _minimal_domain_data() -> dict:
    return {
        "morphology_anatomy_physiology": _domain_data_with_claims("Pseudobulbs present."),
        "habitat": _domain_data_with_claims("Cloud forest epiphyte."),
        "geography": _domain_data_with_claims("Mexico, Guatemala."),
        "pollination": None,  # not fetched → UNAVAILABLE
        "mycorrhizae": {"claims": [], "gap_reason": "Not yet sampled."},
        "literature": _domain_data_with_claims("Reviewed in Dressler 1993."),
        "neighboring_taxa_community": None,
        "conservation": {"claims": [], "gaps": ["No IUCN assessment."]},
    }


def test_build_teaching_synthesis_returns_correct_type():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    assert isinstance(result, TeachingSynthesisV1)


def test_graph_mutation_is_always_false():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    assert result.graph_mutation is False


def test_publication_boundary_is_read_only():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    pb = result.publication_boundary
    assert pb["read_only"] is True
    assert pb["automatic_publication"] is False
    assert pb["knowledge_graph_mutation"] is False


def test_contract_and_schema_versions_correct():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    assert result.contract_version == CONTRACT_VERSION
    assert result.schema_version == SCHEMA_VERSION


def test_all_ordered_domains_appear_in_relationship_model():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    for dom in ORDERED_DOMAINS:
        assert dom in result.relationship_model, f"Domain {dom!r} missing from relationship_model"


def test_all_ordered_domains_appear_in_narrative_segments():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    segment_domains = [s.domain for s in result.narrative_segments]
    for dom in ORDERED_DOMAINS:
        assert dom in segment_domains, f"Domain {dom!r} missing from narrative_segments"


def test_unavailable_domain_in_knowledge_gaps():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    gap_text = " ".join(result.knowledge_gaps)
    # pollination was None → UNAVAILABLE → must appear in gaps
    assert "pollination" in gap_text.lower()


def test_gap_domain_in_knowledge_gaps():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    gap_text = " ".join(result.knowledge_gaps)
    assert "mycorrhizae" in gap_text.lower() or "conservation" in gap_text.lower()


def test_supported_domain_not_in_knowledge_gaps():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    gap_text = " ".join(result.knowledge_gaps)
    assert "morphology" not in gap_text.lower()


def test_provenance_in_evidence_provenance_output():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    # morphology has a claim with source "test-source"
    provenance_sources = [ep.get("source") for ep in result.evidence_provenance]
    assert "test-source" in provenance_sources


def test_contradictions_populated_when_conflict_present():
    data = _minimal_domain_data()
    data["pollination"] = _domain_data_with_claims(
        "Eulaema pollinates.",
        conflicts=["No Eulaema observed."],
    )
    result = build_teaching_synthesis(_subject(), data)
    assert len(result.contradictions) >= 1
    assert any(c["domain"] == "pollination" for c in result.contradictions)


def test_to_dict_serializes_without_error():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["graph_mutation"] is False
    assert "subject" in d
    assert "relationship_model" in d


def test_audience_defaults_to_public():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    assert result.audience == AudienceLevel.PUBLIC


def test_depth_defaults_to_standard():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    assert result.depth == DepthLevel.STANDARD


def test_invalid_audience_falls_back_to_public():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data(), audience="xyzzy")
    assert result.audience == AudienceLevel.PUBLIC


def test_sensitive_locality_policy_withheld_by_default():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    assert result.sensitive_locality_policy["coordinates_withheld"] is True


def test_no_coordinate_fields_in_to_dict_output():
    """Locality safety: coordinate fields must not appear in the serialized output."""
    data = _minimal_domain_data()
    data["geography"] = {
        "claims": [
            {
                "statement": "Found in Mexico.",
                "source_references": [
                    {
                        "source": "gbif",
                        "type": "occurrence",
                        "review_state": "PUBLIC",
                        "latitude": "17.0",
                        "longitude": "-96.5",
                    }
                ],
            }
        ]
    }
    result = build_teaching_synthesis(_subject(), data)
    serialized = str(result.to_dict())
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_fingerprint_stable_for_same_inputs():
    """Same subject + timestamp + audience → same fingerprint."""
    ts = "2026-09-03T12:00:00+00:00"
    r1 = build_teaching_synthesis(
        _subject(), _minimal_domain_data(), generated_at=ts
    )
    r2 = build_teaching_synthesis(
        _subject(), _minimal_domain_data(), generated_at=ts
    )
    assert r1.fingerprint == r2.fingerprint


def test_central_idea_and_objective_preserved():
    result = build_teaching_synthesis(
        _subject(),
        _minimal_domain_data(),
        central_instructional_idea="Orchids depend on precise pollinator-flower geometry.",
        learning_objective="Identify three orchid adaptations for pollinator attraction.",
    )
    assert result.central_instructional_idea is not None
    assert "geometry" in result.central_instructional_idea
    assert result.learning_objective is not None


def test_observable_prompts_preserved():
    prompts = ["Compare the labellum shape.", "Note the color contrast with ambient vegetation."]
    result = build_teaching_synthesis(
        _subject(), _minimal_domain_data(), observable_prompts=prompts
    )
    assert result.observable_prompts == prompts


def test_deeper_routes_default_all_none():
    result = build_teaching_synthesis(_subject(), _minimal_domain_data())
    for key in ("atlas", "matrix", "literature", "university", "research_station", "calyx"):
        assert result.deeper_routes[key] is None


def test_deeper_routes_populated_when_supplied():
    result = build_teaching_synthesis(
        _subject(),
        _minimal_domain_data(),
        deeper_routes={"atlas": "/atlas/laelia-anceps", "university": "/u/laelia"},
    )
    assert result.deeper_routes["atlas"] == "/atlas/laelia-anceps"
    assert result.deeper_routes["university"] == "/u/laelia"
    assert result.deeper_routes["calyx"] is None


# ---------------------------------------------------------------------------
# Featured Genus pool
# ---------------------------------------------------------------------------


def _species_list() -> list[dict]:
    return [
        {"taxon_name": "Laelia anceps", "taxon_id": "sp-001", "has_media": True, "media_attribution": "Attr1"},
        {"taxon_name": "Laelia gouldiana", "taxon_id": "sp-002", "has_media": False, "media_attribution": None},
        {"taxon_name": "Laelia rubescens", "taxon_id": "sp-003", "has_media": True, "media_attribution": "Attr3"},
        {"taxon_name": "Laelia speciosa", "taxon_id": "sp-001", "has_media": True},  # duplicate taxon_id
    ]


def test_featured_pool_deduplication():
    pool = build_featured_genus_pool("Laelia", _species_list())
    assert pool["pool_size"] == 3  # sp-001 appears twice; only first kept


def test_featured_pool_deterministic():
    p1 = build_featured_genus_pool("Laelia", _species_list())
    p2 = build_featured_genus_pool("Laelia", _species_list())
    assert [s["taxon_id"] for s in p1["pool"]] == [s["taxon_id"] for s in p2["pool"]]


def test_featured_pool_canonical_identities_stable():
    pool = build_featured_genus_pool("Laelia", _species_list())
    names = [s["taxon_name"] for s in pool["pool"]]
    # Order is deterministic by sort_key then name; names should be stable.
    assert names == sorted(names)


def test_featured_pool_media_eligibility_honest():
    pool = build_featured_genus_pool("Laelia", _species_list())
    by_id = {s["taxon_id"]: s for s in pool["pool"]}
    assert by_id["sp-001"]["has_media"] is True
    assert by_id["sp-002"]["has_media"] is False
    assert pool["no_media_count"] == 1


def test_featured_pool_no_client_side_inference():
    pool = build_featured_genus_pool("Laelia", _species_list())
    assert pool["rotation_plan"]["client_side_inference_required"] is False
    assert pool["rotation_plan"]["deterministic"] is True


def test_featured_pool_graph_mutation_false():
    pool = build_featured_genus_pool("Laelia", _species_list())
    assert pool["graph_mutation"] is False


def test_featured_pool_rotation_plan_slots():
    pool = build_featured_genus_pool(
        "Laelia", _species_list(), window_hours=12, rotation_interval_seconds=45
    )
    expected_slots = (12 * 3600) // 45
    assert pool["rotation_plan"]["slots_in_window"] == expected_slots


def test_featured_pool_empty_species_list():
    pool = build_featured_genus_pool("Laelia", [])
    assert pool["pool_size"] == 0
    assert pool["pool"] == []
    assert pool["rotation_plan"]["cycles_in_window"] == 0
