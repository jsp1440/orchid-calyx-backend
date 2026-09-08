"""Tests for OC-MOLECULAR-001 — Molecular sequence / GenBank / ITS accession contract.

Covers:
- UNKNOWN fallback (MolecularGateway unavailable, build_unavailable_molecular_matrix)
- CONFLICT integrity (CONFLICT never silently promoted to VERIFIED)
- Fabricated-accession prohibition (ACCESSION_VERIFIED requires non-empty accession_id)
- Binding precedence (ACCESSION_VERIFIED > TAXON_UNRESOLVED > CONFLICT > UNKNOWN)
- Serialization safety
"""
from __future__ import annotations

import json

import pytest

from app.scientific_adapter_lab.molecular_sequence import (
    SCHEMA_VERSION,
    AccessionPresence,
    Locus,
    MolecularGateway,
    SequenceBindingPrecedence,
    SequenceEvidenceState,
    SequenceRecord,
    SequencingMethod,
    build_unavailable_molecular_matrix,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _record(
    record_id: str = "mol-rec-001",
    taxon_id: str = "taxon-001",
    taxon_name: str = "Rhizoctonia solani",
    accession_id: str = "KJ000001.1",
    locus: Locus = Locus.ITS,
    source_authority: str = "GenBank",
    tissue_type: str = "root",
    life_stage: str = "adult",
    sequencing_method: SequencingMethod = SequencingMethod.SANGER,
    evidence_state: SequenceEvidenceState = SequenceEvidenceState.ACCESSION_VERIFIED,
    provenance_chain: tuple[str, ...] = ("genbank:KJ000001.1", "reviewed:2023-01-01"),
) -> SequenceRecord:
    return SequenceRecord(
        record_id=record_id,
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        accession_id=accession_id,
        locus=locus,
        source_authority=source_authority,
        tissue_type=tissue_type,
        life_stage=life_stage,
        sequencing_method=sequencing_method,
        evidence_state=evidence_state,
        provenance_chain=provenance_chain,
    )


# ---------------------------------------------------------------------------
# MolecularGateway — UNKNOWN fallback
# ---------------------------------------------------------------------------


class TestMolecularGateway:
    def test_unavailable_returns_unknown(self):
        gw = MolecularGateway(available=False)
        assert gw.get_accession_presence("taxon-001", Locus.ITS) == AccessionPresence.UNKNOWN

    def test_unavailable_never_returns_present(self):
        gw = MolecularGateway(available=False)
        assert gw.get_accession_presence("any", Locus.ITS) != AccessionPresence.PRESENT

    def test_unavailable_never_returns_absent(self):
        gw = MolecularGateway(available=False)
        assert gw.get_accession_presence("any", Locus.RBCL) != AccessionPresence.ABSENT

    def test_available_raises_not_implemented(self):
        gw = MolecularGateway(available=True)
        with pytest.raises(NotImplementedError, match="MOLECULAR_GATEWAY_NOT_IMPLEMENTED"):
            gw.get_accession_presence("taxon-001", Locus.ITS)

    def test_default_gateway_is_unavailable(self):
        gw = MolecularGateway()
        assert gw.is_available() is False


# ---------------------------------------------------------------------------
# CONFLICT integrity
# ---------------------------------------------------------------------------


class TestConflictIntegrity:
    def test_conflict_record_is_valid(self):
        rec = _record(evidence_state=SequenceEvidenceState.CONFLICT)
        rec.validate()  # must not raise — CONFLICT is a valid state

    def test_conflict_detected_by_precedence(self):
        prec = SequenceBindingPrecedence()
        conflict_rec = _record(evidence_state=SequenceEvidenceState.CONFLICT, record_id="conflict")
        assert prec.is_conflict(conflict_rec) is True

    def test_verified_not_flagged_as_conflict(self):
        prec = SequenceBindingPrecedence()
        verified_rec = _record(evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED)
        assert prec.is_conflict(verified_rec) is False

    def test_conflict_loses_to_verified_in_precedence(self):
        prec = SequenceBindingPrecedence()
        conflict = _record(evidence_state=SequenceEvidenceState.CONFLICT, record_id="c")
        verified = _record(evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED, record_id="v")
        winner = prec.resolve([conflict, verified])
        assert winner.evidence_state == SequenceEvidenceState.ACCESSION_VERIFIED


# ---------------------------------------------------------------------------
# Fabricated-accession prohibition
# ---------------------------------------------------------------------------


class TestFabricatedAccessionProhibition:
    def test_verified_with_empty_accession_raises(self):
        rec = _record(
            evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED,
            accession_id="",
        )
        with pytest.raises(ValueError, match="accession_id"):
            rec.validate()

    def test_verified_with_accession_passes(self):
        rec = _record(
            evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED,
            accession_id="KJ000001.1",
        )
        rec.validate()  # must not raise

    def test_unknown_state_with_empty_accession_is_valid(self):
        rec = _record(
            evidence_state=SequenceEvidenceState.UNKNOWN,
            accession_id="",
        )
        rec.validate()  # must not raise

    def test_empty_record_id_raises(self):
        rec = _record(record_id="")
        with pytest.raises(ValueError, match="record_id"):
            rec.validate()

    def test_empty_taxon_id_raises(self):
        rec = _record(taxon_id="")
        with pytest.raises(ValueError, match="taxon_id"):
            rec.validate()

    def test_empty_provenance_chain_raises(self):
        rec = _record(provenance_chain=())
        with pytest.raises(ValueError, match="provenance_chain"):
            rec.validate()


# ---------------------------------------------------------------------------
# Binding precedence
# ---------------------------------------------------------------------------


class TestSequenceBindingPrecedence:
    def test_verified_beats_taxon_unresolved(self):
        verified = _record(evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED, record_id="v")
        unresolved = _record(evidence_state=SequenceEvidenceState.TAXON_UNRESOLVED, record_id="u")
        prec = SequenceBindingPrecedence()
        winner = prec.resolve([unresolved, verified])
        assert winner.evidence_state == SequenceEvidenceState.ACCESSION_VERIFIED

    def test_verified_beats_fungus_unresolved(self):
        verified = _record(evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED, record_id="v")
        fungus = _record(evidence_state=SequenceEvidenceState.FUNGUS_UNRESOLVED, record_id="f")
        prec = SequenceBindingPrecedence()
        winner = prec.resolve([fungus, verified])
        assert winner.evidence_state == SequenceEvidenceState.ACCESSION_VERIFIED

    def test_taxon_unresolved_beats_conflict(self):
        taxon_u = _record(evidence_state=SequenceEvidenceState.TAXON_UNRESOLVED,
                          accession_id="", record_id="u")
        conflict = _record(evidence_state=SequenceEvidenceState.CONFLICT, record_id="c")
        prec = SequenceBindingPrecedence()
        winner = prec.resolve([conflict, taxon_u])
        assert winner.evidence_state == SequenceEvidenceState.TAXON_UNRESOLVED

    def test_conflict_beats_unknown(self):
        conflict = _record(evidence_state=SequenceEvidenceState.CONFLICT, record_id="c")
        unknown = _record(evidence_state=SequenceEvidenceState.UNKNOWN,
                          accession_id="", record_id="u")
        prec = SequenceBindingPrecedence()
        winner = prec.resolve([unknown, conflict])
        assert winner.evidence_state == SequenceEvidenceState.CONFLICT

    def test_empty_raises(self):
        prec = SequenceBindingPrecedence()
        with pytest.raises(ValueError, match="SEQUENCE_BINDING_EMPTY"):
            prec.resolve([])

    def test_single_record_returned(self):
        rec = _record()
        prec = SequenceBindingPrecedence()
        assert prec.resolve([rec]) is rec

    def test_is_verified_true_for_verified(self):
        prec = SequenceBindingPrecedence()
        assert prec.is_verified(_record(evidence_state=SequenceEvidenceState.ACCESSION_VERIFIED))

    def test_is_verified_false_for_conflict(self):
        prec = SequenceBindingPrecedence()
        assert not prec.is_verified(_record(evidence_state=SequenceEvidenceState.CONFLICT))


# ---------------------------------------------------------------------------
# build_unavailable_molecular_matrix
# ---------------------------------------------------------------------------


class TestBuildUnavailableMolecularMatrix:
    def test_all_unknown_evidence_state(self):
        records = build_unavailable_molecular_matrix(["t1", "t2"])
        assert all(r.evidence_state == SequenceEvidenceState.UNKNOWN for r in records)

    def test_accession_id_empty_not_fabricated(self):
        records = build_unavailable_molecular_matrix(["t1"])
        assert records[0].accession_id == ""

    def test_taxon_ids_preserved(self):
        records = build_unavailable_molecular_matrix(["taxon-A", "taxon-B"])
        assert [r.taxon_id for r in records] == ["taxon-A", "taxon-B"]

    def test_empty_input_returns_empty(self):
        assert build_unavailable_molecular_matrix([]) == []

    def test_default_locus_is_its(self):
        records = build_unavailable_molecular_matrix(["t1"])
        assert records[0].locus == Locus.ITS

    def test_custom_locus_applied(self):
        records = build_unavailable_molecular_matrix(["t1"], locus=Locus.RBCL)
        assert records[0].locus == Locus.RBCL


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestMolecularSerialization:
    def test_schema_version_present(self):
        rec = _record()
        assert rec.to_safe_dict()["schema_version"] == SCHEMA_VERSION

    def test_serialize_roundtrip(self):
        rec = _record()
        parsed = json.loads(rec.serialize_as_json())
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["accession_id"] == "KJ000001.1"
        assert parsed["evidence_state"] == "ACCESSION_VERIFIED"

    def test_unavailable_stubs_serialize(self):
        stubs = build_unavailable_molecular_matrix(["taxon-001"])
        parsed = json.loads(stubs[0].serialize_as_json())
        assert parsed["evidence_state"] == "UNKNOWN"
        assert parsed["accession_id"] == ""

    def test_no_restricted_locality_in_output(self):
        rec = _record()
        raw = rec.serialize_as_json()
        forbidden = {"lat", "lon", "latitude", "longitude", "locality", "collector"}
        parsed = json.loads(raw)
        assert not forbidden & set(parsed.keys())
