"""Tests for OC-KG-001 — Knowledge Graph materialization schema, governed pipeline.

Covers:
- UNKNOWN fallback in KGReadThroughGateway (no fabricated edges)
- Fabricated-zero prohibition (human_review_required always True)
- No auto-publication (KnowledgeGraphPipeline governance enforcement)
- Source precedence (canonical_reviewed > canonical_unreviewed > external_discovery)
- Serialization safety
"""
from __future__ import annotations

import json

import pytest

from app.scientific_adapter_lab.kg_materialization import (
    SCHEMA_VERSION,
    EdgePresence,
    KGEvidenceState,
    KGMaterializationRecord,
    KGReadThroughGateway,
    KGSourcePrecedence,
    KnowledgeGraphPipeline,
    SourceDomain,
    build_unavailable_kg_stubs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _record(
    record_id: str = "kg-rec-001",
    source_domain: SourceDomain = SourceDomain.TAXONOMY,
    evidence_state: KGEvidenceState = KGEvidenceState.CANONICAL_REVIEWED,
    taxon_id: str = "taxon-001",
    taxon_name: str = "Cattleya labiata",
    subject_entity: str = "taxon-001",
    predicate: str = "has_habitat",
    object_entity: str = "cloud_forest",
    provenance_chain: tuple[str, ...] = ("source:idigbio", "reviewed:2023-01-01"),
    human_review_required: bool = True,
) -> KGMaterializationRecord:
    return KGMaterializationRecord(
        record_id=record_id,
        source_domain=source_domain,
        evidence_state=evidence_state,
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        subject_entity=subject_entity,
        predicate=predicate,
        object_entity=object_entity,
        provenance_chain=provenance_chain,
        human_review_required=human_review_required,
    )


# ---------------------------------------------------------------------------
# KnowledgeGraphPipeline — governance enforcement (no auto-publication)
# ---------------------------------------------------------------------------


class TestKnowledgeGraphPipelineGovernance:
    def test_default_pipeline_is_valid(self):
        p = KnowledgeGraphPipeline()
        assert p.automatic_publication is False
        assert p.knowledge_graph_mutation is False

    def test_automatic_publication_true_raises(self):
        with pytest.raises(ValueError, match="automatic_publication"):
            KnowledgeGraphPipeline(automatic_publication=True)

    def test_knowledge_graph_mutation_true_raises(self):
        with pytest.raises(ValueError, match="knowledge_graph_mutation"):
            KnowledgeGraphPipeline(knowledge_graph_mutation=True)

    def test_governance_violation_message_contains_sentinel(self):
        with pytest.raises(ValueError, match="KG_PIPELINE_GOVERNANCE_VIOLATION"):
            KnowledgeGraphPipeline(automatic_publication=True)


# ---------------------------------------------------------------------------
# KGReadThroughGateway — UNKNOWN fallback, no fabricated edges
# ---------------------------------------------------------------------------


class TestKGReadThroughGateway:
    def test_unavailable_gateway_returns_unknown(self):
        gw = KGReadThroughGateway(available=False)
        result = gw.get_edge_presence("taxon-001", "has_habitat", "cloud_forest")
        assert result == EdgePresence.UNKNOWN

    def test_unavailable_gateway_never_returns_present(self):
        gw = KGReadThroughGateway(available=False)
        result = gw.get_edge_presence("any", "any", "any")
        assert result != EdgePresence.PRESENT

    def test_unavailable_gateway_never_returns_absent(self):
        gw = KGReadThroughGateway(available=False)
        result = gw.get_edge_presence("any", "any", "any")
        assert result != EdgePresence.ABSENT

    def test_is_available_false_when_unavailable(self):
        gw = KGReadThroughGateway(available=False)
        assert gw.is_available() is False

    def test_available_gateway_raises_not_implemented(self):
        gw = KGReadThroughGateway(available=True)
        with pytest.raises(NotImplementedError, match="KG_READ_THROUGH_NOT_IMPLEMENTED"):
            gw.get_edge_presence("any", "any", "any")

    def test_default_gateway_is_unavailable(self):
        gw = KGReadThroughGateway()
        assert gw.is_available() is False


# ---------------------------------------------------------------------------
# KGMaterializationRecord — fabricated-zero prohibition
# ---------------------------------------------------------------------------


class TestKGMaterializationRecordValidation:
    def test_valid_record_passes(self):
        rec = _record()
        rec.validate()  # must not raise

    def test_empty_record_id_raises(self):
        rec = _record(record_id="")
        with pytest.raises(ValueError, match="record_id"):
            rec.validate()

    def test_human_review_false_raises(self):
        rec = _record(human_review_required=False)
        with pytest.raises(ValueError, match="human_review_required"):
            rec.validate()

    def test_empty_provenance_chain_raises(self):
        rec = _record(provenance_chain=())
        with pytest.raises(ValueError, match="provenance_chain"):
            rec.validate()

    def test_record_is_immutable(self):
        rec = _record()
        with pytest.raises(Exception):
            rec.record_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Source precedence
# ---------------------------------------------------------------------------


class TestKGSourcePrecedence:
    def test_canonical_reviewed_beats_canonical_unreviewed(self):
        reviewed = _record(evidence_state=KGEvidenceState.CANONICAL_REVIEWED, record_id="r1")
        unreviewed = _record(evidence_state=KGEvidenceState.CANONICAL_UNREVIEWED, record_id="r2")
        prec = KGSourcePrecedence()
        winner = prec.resolve([unreviewed, reviewed])
        assert winner.evidence_state == KGEvidenceState.CANONICAL_REVIEWED

    def test_canonical_reviewed_beats_external_discovery(self):
        reviewed = _record(evidence_state=KGEvidenceState.CANONICAL_REVIEWED, record_id="r1")
        external = _record(evidence_state=KGEvidenceState.EXTERNAL_DISCOVERY, record_id="r2")
        prec = KGSourcePrecedence()
        winner = prec.resolve([external, reviewed])
        assert winner.evidence_state == KGEvidenceState.CANONICAL_REVIEWED

    def test_canonical_unreviewed_beats_external_discovery(self):
        unreviewed = _record(evidence_state=KGEvidenceState.CANONICAL_UNREVIEWED, record_id="r1")
        external = _record(evidence_state=KGEvidenceState.EXTERNAL_DISCOVERY, record_id="r2")
        prec = KGSourcePrecedence()
        winner = prec.resolve([external, unreviewed])
        assert winner.evidence_state == KGEvidenceState.CANONICAL_UNREVIEWED

    def test_any_beats_unavailable(self):
        external = _record(evidence_state=KGEvidenceState.EXTERNAL_DISCOVERY, record_id="r1")
        unavail = _record(evidence_state=KGEvidenceState.UNAVAILABLE, record_id="r2")
        prec = KGSourcePrecedence()
        winner = prec.resolve([unavail, external])
        assert winner.evidence_state == KGEvidenceState.EXTERNAL_DISCOVERY

    def test_single_record_returned(self):
        rec = _record()
        prec = KGSourcePrecedence()
        assert prec.resolve([rec]) is rec

    def test_empty_raises(self):
        prec = KGSourcePrecedence()
        with pytest.raises(ValueError, match="KG_PRECEDENCE_EMPTY"):
            prec.resolve([])

    def test_is_authoritative_true_for_reviewed(self):
        rec = _record(evidence_state=KGEvidenceState.CANONICAL_REVIEWED)
        prec = KGSourcePrecedence()
        assert prec.is_authoritative(rec) is True

    def test_is_authoritative_false_for_unreviewed(self):
        rec = _record(evidence_state=KGEvidenceState.CANONICAL_UNREVIEWED)
        prec = KGSourcePrecedence()
        assert prec.is_authoritative(rec) is False


# ---------------------------------------------------------------------------
# build_unavailable_kg_stubs
# ---------------------------------------------------------------------------


class TestBuildUnavailableKgStubs:
    def test_returns_unavailable_evidence_for_each_taxon(self):
        stubs = build_unavailable_kg_stubs(["t1", "t2"])
        assert all(r.evidence_state == KGEvidenceState.UNAVAILABLE for r in stubs)

    def test_human_review_required_is_true(self):
        stubs = build_unavailable_kg_stubs(["t1"])
        assert stubs[0].human_review_required is True

    def test_object_entity_is_unknown(self):
        stubs = build_unavailable_kg_stubs(["t1"])
        assert stubs[0].object_entity == EdgePresence.UNKNOWN.value

    def test_taxon_ids_preserved(self):
        stubs = build_unavailable_kg_stubs(["taxon-A", "taxon-B"])
        assert [s.taxon_id for s in stubs] == ["taxon-A", "taxon-B"]

    def test_empty_input_returns_empty(self):
        assert build_unavailable_kg_stubs([]) == []

    def test_provenance_chain_is_non_empty(self):
        stubs = build_unavailable_kg_stubs(["t1"])
        assert len(stubs[0].provenance_chain) > 0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestKGSerialization:
    def test_to_safe_dict_has_schema_version(self):
        rec = _record()
        d = rec.to_safe_dict()
        assert d["schema_version"] == SCHEMA_VERSION

    def test_to_safe_dict_has_evidence_state(self):
        rec = _record(evidence_state=KGEvidenceState.CANONICAL_REVIEWED)
        d = rec.to_safe_dict()
        assert d["evidence_state"] == "canonical_reviewed"

    def test_serialize_as_json_roundtrip(self):
        rec = _record()
        raw = rec.serialize_as_json()
        parsed = json.loads(raw)
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["taxon_id"] == "taxon-001"
        assert parsed["human_review_required"] is True

    def test_unavailable_stubs_serialize_correctly(self):
        stubs = build_unavailable_kg_stubs(["taxon-001"])
        raw = stubs[0].serialize_as_json()
        parsed = json.loads(raw)
        assert parsed["evidence_state"] == "UNAVAILABLE"
        assert parsed["human_review_required"] is True

    def test_serialization_no_credentials_in_output(self):
        rec = _record()
        raw = rec.serialize_as_json()
        for forbidden in ("password", "secret", "api_key", "token", "credential"):
            assert forbidden not in raw.lower()
