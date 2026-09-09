"""Tests for OC-COMPLETE-009 Scientific Adapter Laboratory — interaction pipeline.

Covers the GloBI interaction adapter and capability candidate matrix, proving:
- source → normalization → canonical taxon reconciliation → evidence/provenance
  → review/KG-candidate pipeline without scientific auto-promotion
- UNKNOWN fallback when data is unavailable (never fabricate)
- Governance invariants: review_required, auto_promotion_blocked, graph_mutation=False
- Machine-readable candidate matrix with required tool evaluations
- Serialization safety (JSON round-trip, no credential fields)
"""
import json

import pytest

from app.scientific_adapter_lab.interaction_laboratory import (
    SCHEMA_VERSION,
    CapabilityCandidateMatrix,
    CandidateTool,
    InteractionEvidenceState,
    InteractionGateway,
    InteractionSource,
    InteractionType,
    KGCandidateInteraction,
    NormalizedInteraction,
    RawInteractionRecord,
    ToolEvaluation,
    build_gloBi_candidate_matrix,
    build_unavailable_interaction,
    map_interaction_type,
    normalize_interaction,
    resolve_interaction_precedence,
    stage_interaction_for_review,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _raw_pollinator(
    *,
    record_id: str = "gloBi-001",
    source_taxon: str = "Phalaenopsis amabilis",
    target_taxon: str = "Apis mellifera",
    interaction_type_id: str = "RO:0002455",
    provider: InteractionSource = InteractionSource.GLOBI,
) -> RawInteractionRecord:
    return RawInteractionRecord(
        record_id=record_id,
        source_taxon_name=source_taxon,
        target_taxon_name=target_taxon,
        interaction_type_name="pollinates",
        interaction_type_id=interaction_type_id,
        citation="Dressler 1981 doi:10.0000/test",
        dataset_name="globi-orchidaceae",
        dataset_doi="10.5281/zenodo.test",
        provider=provider,
    )


def _normalized(
    *,
    evidence_state: InteractionEvidenceState = InteractionEvidenceState.VERIFIED,
    taxon_resolved: bool = True,
) -> NormalizedInteraction:
    return NormalizedInteraction(
        record_id="n-001",
        source_taxon_name="Phalaenopsis amabilis",
        source_taxon_id="oc-taxon-123" if taxon_resolved else "",
        target_taxon_name="Apis mellifera",
        target_taxon_id="oc-taxon-456" if taxon_resolved else "",
        interaction_type=InteractionType.POLLINATES,
        evidence_state=evidence_state,
        citation="Dressler 1981",
        dataset_source=InteractionSource.GLOBI,
        provenance_chain=("globi-orchidaceae", "10.5281/zenodo.test", "GloBI"),
        taxon_resolved=taxon_resolved,
    )


# ---------------------------------------------------------------------------
# TestRawInteractionRecord
# ---------------------------------------------------------------------------

class TestRawInteractionRecord:
    def test_valid_record_passes_validation(self):
        raw = _raw_pollinator()
        raw.validate()  # must not raise

    def test_empty_record_id_raises(self):
        raw = _raw_pollinator(record_id="")
        with pytest.raises(ValueError, match="record_id"):
            raw.validate()

    def test_empty_source_taxon_raises(self):
        raw = _raw_pollinator(source_taxon="")
        with pytest.raises(ValueError, match="source_taxon_name"):
            raw.validate()

    def test_empty_target_taxon_raises(self):
        raw = _raw_pollinator(target_taxon="")
        with pytest.raises(ValueError, match="target_taxon_name"):
            raw.validate()

    def test_empty_both_type_fields_raises(self):
        raw = RawInteractionRecord(
            record_id="r1",
            source_taxon_name="Phalaenopsis amabilis",
            target_taxon_name="Apis mellifera",
            interaction_type_name="",
            interaction_type_id="",
            citation="",
            dataset_name="test",
            dataset_doi="",
            provider=InteractionSource.GLOBI,
        )
        with pytest.raises(ValueError, match="interaction type"):
            raw.validate()

    def test_record_is_immutable(self):
        raw = _raw_pollinator()
        with pytest.raises((AttributeError, TypeError)):
            raw.record_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestMapInteractionType
# ---------------------------------------------------------------------------

class TestMapInteractionType:
    def test_ro_id_pollinates(self):
        assert map_interaction_type("RO:0002455") is InteractionType.POLLINATES

    def test_ro_id_pollinated_by(self):
        assert map_interaction_type("RO:0002456") is InteractionType.POLLINATED_BY

    def test_ro_id_visits_flowers(self):
        assert map_interaction_type("RO:0002472") is InteractionType.VISITS_FLOWERS_OF

    def test_ro_id_symbiont(self):
        assert map_interaction_type("RO:0002622") is InteractionType.SYMBIONT_OF

    def test_ro_id_parasite(self):
        assert map_interaction_type("RO:0002453") is InteractionType.PARASITE_OF

    def test_name_pollinates(self):
        assert map_interaction_type("pollinates") is InteractionType.POLLINATES

    def test_name_symbiont_of(self):
        assert map_interaction_type("symbiont of") is InteractionType.SYMBIONT_OF

    def test_name_is_symbiont_of(self):
        assert map_interaction_type("is symbiont of") is InteractionType.SYMBIONT_OF

    def test_unknown_term_returns_unknown(self):
        assert map_interaction_type("fights with") is InteractionType.UNKNOWN_INTERACTION

    def test_whitespace_stripped(self):
        assert map_interaction_type("  pollinates  ") is InteractionType.POLLINATES


# ---------------------------------------------------------------------------
# TestNormalizeInteraction
# ---------------------------------------------------------------------------

class TestNormalizeInteraction:
    def test_both_taxa_resolved_gives_verified(self):
        raw = _raw_pollinator()
        result = normalize_interaction(
            raw,
            source_taxon_id="oc-taxon-123",
            target_taxon_id="oc-taxon-456",
        )
        assert result.evidence_state is InteractionEvidenceState.VERIFIED
        assert result.taxon_resolved is True

    def test_missing_source_id_gives_provisional(self):
        raw = _raw_pollinator()
        result = normalize_interaction(raw, target_taxon_id="oc-taxon-456")
        assert result.evidence_state is InteractionEvidenceState.PROVISIONAL
        assert result.taxon_resolved is False

    def test_missing_target_id_gives_provisional(self):
        raw = _raw_pollinator()
        result = normalize_interaction(raw, source_taxon_id="oc-taxon-123")
        assert result.evidence_state is InteractionEvidenceState.PROVISIONAL
        assert result.taxon_resolved is False

    def test_no_ids_gives_provisional(self):
        raw = _raw_pollinator()
        result = normalize_interaction(raw)
        assert result.evidence_state is InteractionEvidenceState.PROVISIONAL

    def test_unavailable_provider_gives_unknown(self):
        raw = _raw_pollinator(provider=InteractionSource.UNAVAILABLE)
        result = normalize_interaction(
            raw,
            source_taxon_id="oc-taxon-123",
            target_taxon_id="oc-taxon-456",
        )
        assert result.evidence_state is InteractionEvidenceState.UNKNOWN

    def test_interaction_type_mapped_from_ro_id(self):
        raw = _raw_pollinator(interaction_type_id="RO:0002455")
        result = normalize_interaction(raw)
        assert result.interaction_type is InteractionType.POLLINATES

    def test_interaction_type_falls_back_to_name(self):
        raw = RawInteractionRecord(
            record_id="r1",
            source_taxon_name="Phalaenopsis amabilis",
            target_taxon_name="Apis mellifera",
            interaction_type_name="symbiont of",
            interaction_type_id="",
            citation="test",
            dataset_name="test-ds",
            dataset_doi="",
            provider=InteractionSource.GLOBI,
        )
        result = normalize_interaction(raw)
        assert result.interaction_type is InteractionType.SYMBIONT_OF

    def test_provenance_chain_preserved(self):
        raw = _raw_pollinator()
        result = normalize_interaction(raw)
        assert "globi-orchidaceae" in result.provenance_chain
        assert "GloBI" in result.provenance_chain

    def test_citation_preserved(self):
        raw = _raw_pollinator()
        result = normalize_interaction(raw)
        assert "Dressler" in result.citation

    def test_result_is_immutable(self):
        raw = _raw_pollinator()
        result = normalize_interaction(raw)
        with pytest.raises((AttributeError, TypeError)):
            result.record_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestNormalizedInteractionValidate
# ---------------------------------------------------------------------------

class TestNormalizedInteractionValidate:
    def test_verified_with_resolved_taxon_passes(self):
        n = _normalized(evidence_state=InteractionEvidenceState.VERIFIED, taxon_resolved=True)
        n.validate()  # must not raise

    def test_verified_without_resolved_taxon_raises(self):
        n = _normalized(evidence_state=InteractionEvidenceState.VERIFIED, taxon_resolved=False)
        with pytest.raises(ValueError, match="VERIFIED_STATE_REQUIRES_RESOLVED_TAXON"):
            n.validate()

    def test_provisional_without_resolved_taxon_passes(self):
        n = _normalized(evidence_state=InteractionEvidenceState.PROVISIONAL, taxon_resolved=False)
        n.validate()  # must not raise


# ---------------------------------------------------------------------------
# TestKGCandidateInteraction
# ---------------------------------------------------------------------------

class TestKGCandidateInteraction:
    def test_default_candidate_has_correct_invariants(self):
        n = _normalized()
        candidate = stage_interaction_for_review(n)
        assert candidate.review_required is True
        assert candidate.auto_promotion_blocked is True
        assert candidate.graph_mutation is False
        assert candidate.candidate_state == "PENDING_REVIEW"

    def test_review_required_false_raises(self):
        n = _normalized()
        with pytest.raises(PermissionError, match="REVIEW_REQUIRED"):
            KGCandidateInteraction(normalized=n, review_required=False)

    def test_auto_promotion_blocked_false_raises(self):
        n = _normalized()
        with pytest.raises(PermissionError, match="AUTO_PROMOTION_BLOCKED"):
            KGCandidateInteraction(normalized=n, auto_promotion_blocked=False)

    def test_graph_mutation_true_raises(self):
        n = _normalized()
        with pytest.raises(PermissionError, match="GRAPH_MUTATION"):
            KGCandidateInteraction(normalized=n, graph_mutation=True)

    def test_stage_requires_valid_normalized(self):
        n = _normalized(evidence_state=InteractionEvidenceState.VERIFIED, taxon_resolved=False)
        with pytest.raises(ValueError, match="VERIFIED_STATE_REQUIRES_RESOLVED_TAXON"):
            stage_interaction_for_review(n)


# ---------------------------------------------------------------------------
# TestBuildUnavailableInteraction
# ---------------------------------------------------------------------------

class TestBuildUnavailableInteraction:
    def test_returns_unknown_state(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.evidence_state is InteractionEvidenceState.UNKNOWN

    def test_preserves_taxon_name(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.source_taxon_name == "Phalaenopsis amabilis"

    def test_target_taxon_name_is_empty(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.target_taxon_name == ""

    def test_source_taxon_id_is_empty(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.source_taxon_id == ""

    def test_interaction_type_is_unknown(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.interaction_type is InteractionType.UNKNOWN_INTERACTION

    def test_taxon_resolved_is_false(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.taxon_resolved is False

    def test_dataset_source_is_unavailable(self):
        result = build_unavailable_interaction("Phalaenopsis amabilis")
        assert result.dataset_source is InteractionSource.UNAVAILABLE


# ---------------------------------------------------------------------------
# TestResolveInteractionPrecedence
# ---------------------------------------------------------------------------

class TestResolveInteractionPrecedence:
    def test_verified_beats_provisional(self):
        verified = _normalized(evidence_state=InteractionEvidenceState.VERIFIED)
        provisional = _normalized(evidence_state=InteractionEvidenceState.PROVISIONAL, taxon_resolved=False)
        result = resolve_interaction_precedence([provisional, verified])
        assert result is not None
        assert result.evidence_state is InteractionEvidenceState.VERIFIED

    def test_provisional_beats_unknown(self):
        provisional = _normalized(evidence_state=InteractionEvidenceState.PROVISIONAL, taxon_resolved=False)
        unknown = build_unavailable_interaction("Phalaenopsis amabilis")
        result = resolve_interaction_precedence([unknown, provisional])
        assert result is not None
        assert result.evidence_state is InteractionEvidenceState.PROVISIONAL

    def test_empty_list_returns_none(self):
        assert resolve_interaction_precedence([]) is None

    def test_single_entry_returned(self):
        n = _normalized()
        result = resolve_interaction_precedence([n])
        assert result is n

    def test_all_unknown_returns_unknown(self):
        u1 = build_unavailable_interaction("Phalaenopsis amabilis")
        u2 = build_unavailable_interaction("Phalaenopsis amabilis")
        result = resolve_interaction_precedence([u1, u2])
        assert result is not None
        assert result.evidence_state is InteractionEvidenceState.UNKNOWN


# ---------------------------------------------------------------------------
# TestSerializationSafety
# ---------------------------------------------------------------------------

class TestSerializationSafety:
    def test_json_round_trip(self):
        raw = _raw_pollinator()
        n = normalize_interaction(raw, source_taxon_id="oc-123", target_taxon_id="oc-456")
        serialized = n.serialize_as_json()
        parsed = json.loads(serialized)
        assert parsed["record_id"] == n.record_id
        assert parsed["evidence_state"] == n.evidence_state.value

    def test_to_safe_dict_has_no_credential_fields(self):
        raw = _raw_pollinator()
        n = normalize_interaction(raw)
        d = n.to_safe_dict()
        forbidden = {"password", "token", "secret", "key", "credential", "api_key"}
        assert not (set(d.keys()) & forbidden)

    def test_unknown_fallback_serializes(self):
        u = build_unavailable_interaction("Phalaenopsis amabilis")
        parsed = json.loads(u.serialize_as_json())
        assert parsed["evidence_state"] == "UNKNOWN"
        assert parsed["source_taxon_id"] is None

    def test_provenance_chain_in_output(self):
        raw = _raw_pollinator()
        n = normalize_interaction(raw)
        d = n.to_safe_dict()
        assert isinstance(d["provenance_chain"], list)
        assert len(d["provenance_chain"]) > 0


# ---------------------------------------------------------------------------
# TestInteractionGateway
# ---------------------------------------------------------------------------

class TestInteractionGateway:
    def test_unavailable_gateway_returns_unknown(self):
        gw = InteractionGateway(available=False)
        results = gw.fetch_orchid_interactions("Phalaenopsis amabilis")
        assert len(results) == 1
        assert results[0].evidence_state is InteractionEvidenceState.UNKNOWN

    def test_available_gateway_raises_not_implemented(self):
        gw = InteractionGateway(available=True)
        with pytest.raises(NotImplementedError):
            gw.fetch_orchid_interactions("Phalaenopsis amabilis")


# ---------------------------------------------------------------------------
# TestCapabilityCandidateMatrix
# ---------------------------------------------------------------------------

class TestCapabilityCandidateMatrix:
    def test_matrix_has_correct_schema_version(self):
        matrix = build_gloBi_candidate_matrix()
        assert matrix.schema_version == SCHEMA_VERSION

    def test_matrix_has_globi_entry(self):
        matrix = build_gloBi_candidate_matrix()
        repos = [c.repo for c in matrix.candidates]
        assert "globalbioticinteractions/globalbioticinteractions" in repos

    def test_matrix_has_nomer_entry(self):
        matrix = build_gloBi_candidate_matrix()
        tools = [c.tool_name for c in matrix.candidates]
        assert "nomer" in tools

    def test_matrix_has_elton_entry(self):
        matrix = build_gloBi_candidate_matrix()
        tools = [c.tool_name for c in matrix.candidates]
        assert "elton" in tools

    def test_matrix_has_ro_ontology_entry(self):
        matrix = build_gloBi_candidate_matrix()
        repos = [c.repo for c in matrix.candidates]
        assert "oborel/obo-relations" in repos

    def test_globi_evaluated_as_federate(self):
        matrix = build_gloBi_candidate_matrix()
        globi = next(
            c for c in matrix.candidates
            if c.repo == "globalbioticinteractions/globalbioticinteractions"
        )
        assert globi.evaluation is ToolEvaluation.FEDERATE

    def test_nomer_evaluated_as_adapt(self):
        matrix = build_gloBi_candidate_matrix()
        nomer = next(c for c in matrix.candidates if c.tool_name == "nomer")
        assert nomer.evaluation is ToolEvaluation.ADAPT

    def test_matrix_has_no_keep_without_implementation(self):
        matrix = build_gloBi_candidate_matrix()
        kept = matrix.by_evaluation(ToolEvaluation.KEEP)
        # No tool should be KEEP unless actually integrated
        assert len(kept) == 0

    def test_matrix_total_count_accurate(self):
        matrix = build_gloBi_candidate_matrix()
        d = matrix.to_safe_dict()
        assert d["total"] == len(matrix.candidates)

    def test_matrix_serializes_as_valid_json(self):
        matrix = build_gloBi_candidate_matrix()
        serialized = matrix.serialize_as_json()
        parsed = json.loads(serialized)
        assert "candidates" in parsed
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_candidate_to_safe_dict_no_credentials(self):
        matrix = build_gloBi_candidate_matrix()
        for c in matrix.candidates:
            d = c.to_safe_dict()
            forbidden = {"password", "token", "secret", "key", "credential"}
            assert not (set(d.keys()) & forbidden)

    def test_all_candidates_have_orchid_relevance(self):
        matrix = build_gloBi_candidate_matrix()
        for c in matrix.candidates:
            assert c.orchid_relevance, f"Missing orchid_relevance for {c.tool_name}"

    def test_all_candidates_have_reuse_pattern(self):
        matrix = build_gloBi_candidate_matrix()
        for c in matrix.candidates:
            assert c.reuse_pattern, f"Missing reuse_pattern for {c.tool_name}"

    def test_add_candidate_increases_count(self):
        matrix = CapabilityCandidateMatrix()
        initial = len(matrix.candidates)
        matrix.add(CandidateTool(
            repo="test/repo",
            tool_name="test-tool",
            license="MIT",
            evaluation=ToolEvaluation.REJECT,
            capability_summary="test",
            reuse_pattern="none",
            orchid_relevance="none",
            rejection_reason="out of scope",
        ))
        assert len(matrix.candidates) == initial + 1

    def test_by_evaluation_filters_correctly(self):
        matrix = build_gloBi_candidate_matrix()
        federate = matrix.by_evaluation(ToolEvaluation.FEDERATE)
        assert all(c.evaluation is ToolEvaluation.FEDERATE for c in federate)


# ---------------------------------------------------------------------------
# TestPipelineEndToEnd
# ---------------------------------------------------------------------------

class TestPipelineEndToEnd:
    """Prove source → normalization → taxon reconciliation → evidence/provenance
    → review/KG-candidate pipeline without auto-promotion."""

    def test_full_pipeline_verified(self):
        # Source: raw GloBI record
        raw = _raw_pollinator()

        # Normalization with canonical taxon IDs (simulating resolver)
        normalized = normalize_interaction(
            raw,
            source_taxon_id="oc-taxon-phal-001",
            target_taxon_id="oc-taxon-apis-001",
        )

        # Evidence state is VERIFIED
        assert normalized.evidence_state is InteractionEvidenceState.VERIFIED

        # Provenance preserved
        assert "globi-orchidaceae" in normalized.provenance_chain
        assert normalized.citation == "Dressler 1981 doi:10.0000/test"

        # Stage for review (no auto-promotion)
        candidate = stage_interaction_for_review(normalized)
        assert candidate.candidate_state == "PENDING_REVIEW"
        assert candidate.review_required is True
        assert candidate.auto_promotion_blocked is True
        assert candidate.graph_mutation is False

    def test_full_pipeline_provisional_when_taxon_unresolved(self):
        raw = _raw_pollinator()
        normalized = normalize_interaction(raw)  # no taxon IDs
        assert normalized.evidence_state is InteractionEvidenceState.PROVISIONAL
        assert normalized.taxon_resolved is False
        # Can still stage for review
        candidate = stage_interaction_for_review(normalized)
        assert candidate.review_required is True

    def test_unavailable_data_returns_unknown_not_fabricated(self):
        gw = InteractionGateway(available=False)
        results = gw.fetch_orchid_interactions(
            "Phalaenopsis amabilis",
            interaction_type=InteractionType.POLLINATES,
        )
        assert len(results) == 1
        assert results[0].evidence_state is InteractionEvidenceState.UNKNOWN
        assert results[0].source_taxon_id == ""
        assert results[0].target_taxon_name == ""

    def test_precedence_resolver_in_pipeline(self):
        raw = _raw_pollinator()
        verified = normalize_interaction(
            raw, source_taxon_id="oc-123", target_taxon_id="oc-456"
        )
        provisional = normalize_interaction(raw)
        unknown = build_unavailable_interaction("Phalaenopsis amabilis")
        best = resolve_interaction_precedence([unknown, provisional, verified])
        assert best is not None
        assert best.evidence_state is InteractionEvidenceState.VERIFIED

    def test_candidate_matrix_present_in_pipeline_output(self):
        matrix = build_gloBi_candidate_matrix()
        federate = matrix.by_evaluation(ToolEvaluation.FEDERATE)
        adapt = matrix.by_evaluation(ToolEvaluation.ADAPT)
        # GloBI data is FEDERATE; nomer/RO are ADAPT
        assert len(federate) >= 1
        assert len(adapt) >= 2
