"""OC-MOLECULAR-001 — Molecular sequence / GenBank / ITS accession integration contract.

Governed molecular-sequence schema and read-through contract binding GenBank/ITS
accession records to canonical orchid taxonomy and mycorrhizal fungus identities.

Key invariants:
- CONFLICT is never silently resolved as VERIFIED; explicit resolution is required.
- UNKNOWN is the correct sentinel when sequence DB is absent; no accession fabricated.
- Verified accession + reviewed taxon outranks unverified or provisional bindings.
- No live GenBank/NCBI API required; MolecularGateway uses an explicit unavailable stub.
- No production DB mutation, no taxonomy activation, no automated publication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA_VERSION = "oc-molecular-sequence/v1"


class Locus(str, Enum):
    ITS = "ITS"
    RBCL = "rbcL"
    MATK = "matK"
    OTHER = "other"
    UNKNOWN_LOCUS = "UNKNOWN_LOCUS"


class SequencingMethod(str, Enum):
    SANGER = "Sanger"
    NGS = "NGS"
    METABARCODING = "metabarcoding"
    UNKNOWN_METHOD = "UNKNOWN_METHOD"


class SequenceEvidenceState(str, Enum):
    ACCESSION_VERIFIED = "ACCESSION_VERIFIED"
    TAXON_UNRESOLVED = "TAXON_UNRESOLVED"
    FUNGUS_UNRESOLVED = "FUNGUS_UNRESOLVED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class AccessionPresence(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


_BINDING_PRECEDENCE = {
    SequenceEvidenceState.ACCESSION_VERIFIED: 4,
    SequenceEvidenceState.TAXON_UNRESOLVED: 2,
    SequenceEvidenceState.FUNGUS_UNRESOLVED: 2,
    SequenceEvidenceState.CONFLICT: 1,
    SequenceEvidenceState.UNKNOWN: 0,
}


@dataclass(frozen=True)
class SequenceRecord:
    """Immutable molecular sequence record bound to a taxon and accession."""

    record_id: str
    taxon_id: str
    taxon_name: str
    accession_id: str           # GenBank/NCBI accession or "" when unavailable
    locus: Locus
    source_authority: str       # e.g. "GenBank", "BOLD", "unavailable"
    tissue_type: str            # e.g. "leaf", "root", "mycorrhizal"
    life_stage: str             # e.g. "adult", "seedling", "unknown"
    sequencing_method: SequencingMethod
    evidence_state: SequenceEvidenceState
    provenance_chain: tuple[str, ...]

    def validate(self) -> None:
        if not self.record_id:
            raise ValueError("SEQUENCE_RECORD_INVALID: record_id must not be empty")
        if not self.taxon_id:
            raise ValueError("SEQUENCE_RECORD_INVALID: taxon_id must not be empty")
        if (
            self.evidence_state == SequenceEvidenceState.ACCESSION_VERIFIED
            and not self.accession_id
        ):
            raise ValueError(
                "SEQUENCE_RECORD_INVALID: ACCESSION_VERIFIED evidence_state requires "
                "a non-empty accession_id"
            )
        if self.evidence_state == SequenceEvidenceState.CONFLICT:
            # CONFLICT must remain CONFLICT; callers may not silently promote it
            pass  # CONFLICT is always valid — it must be resolved explicitly, not here
        if not self.provenance_chain:
            raise ValueError("SEQUENCE_RECORD_INVALID: provenance_chain must not be empty")

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "record_id": self.record_id,
            "taxon_id": self.taxon_id,
            "taxon_name": self.taxon_name,
            "accession_id": self.accession_id,
            "locus": self.locus.value,
            "source_authority": self.source_authority,
            "tissue_type": self.tissue_type,
            "life_stage": self.life_stage,
            "sequencing_method": self.sequencing_method.value,
            "evidence_state": self.evidence_state.value,
            "provenance_chain": list(self.provenance_chain),
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


class MolecularGateway:
    """Read-through gateway for molecular/sequence data.

    Returns UNKNOWN when the sequence DB is unavailable. Never fabricates
    the presence of ITS accessions or any other sequence record.
    """

    def __init__(self, *, available: bool = False) -> None:
        self._available = available

    def get_accession_presence(self, taxon_id: str, locus: Locus) -> AccessionPresence:
        """Return accession presence, defaulting to UNKNOWN when DB unavailable.

        Args:
            taxon_id: Taxon to look up.
            locus: Target locus (ITS, rbcL, etc.).

        Returns:
            AccessionPresence.UNKNOWN in stub/unavailable mode.
        """
        if not self._available:
            return AccessionPresence.UNKNOWN
        raise NotImplementedError(
            "MOLECULAR_GATEWAY_NOT_IMPLEMENTED: real sequence DB connectivity not available "
            "in this slice; use stub (available=False) or connect a real GenBank adapter"
        )

    def is_available(self) -> bool:
        return self._available


class SequenceBindingPrecedence:
    """Arbitrates between competing sequence records for the same taxon/locus.

    Rule: ACCESSION_VERIFIED > TAXON_UNRESOLVED|FUNGUS_UNRESOLVED > CONFLICT > UNKNOWN.
    CONFLICT is never silently promoted to VERIFIED.
    """

    def resolve(self, records: list[SequenceRecord]) -> SequenceRecord:
        if not records:
            raise ValueError("SEQUENCE_BINDING_EMPTY: at least one record required")
        winner = max(records, key=lambda r: _BINDING_PRECEDENCE.get(r.evidence_state, 0))
        return winner

    def is_conflict(self, record: SequenceRecord) -> bool:
        return record.evidence_state == SequenceEvidenceState.CONFLICT

    def is_verified(self, record: SequenceRecord) -> bool:
        return record.evidence_state == SequenceEvidenceState.ACCESSION_VERIFIED


def build_unavailable_molecular_matrix(
    taxon_ids: list[str],
    *,
    locus: Locus = Locus.ITS,
) -> list[SequenceRecord]:
    """Return all-UNKNOWN records when the sequence DB is absent.

    No accession is fabricated. Each returned record has
    SequenceEvidenceState.UNKNOWN and an empty accession_id.

    Args:
        taxon_ids: Taxon IDs to build unavailable stubs for.
        locus: Locus to use in the stubs (default ITS).

    Returns:
        A list of SequenceRecord with evidence_state=UNKNOWN for every
        requested taxon_id.
    """
    return [
        SequenceRecord(
            record_id=f"unavailable:{tid}:{locus.value}",
            taxon_id=tid,
            taxon_name="",
            accession_id="",
            locus=locus,
            source_authority="NO_DB_CONNECTION",
            tissue_type="unknown",
            life_stage="unknown",
            sequencing_method=SequencingMethod.UNKNOWN_METHOD,
            evidence_state=SequenceEvidenceState.UNKNOWN,
            provenance_chain=("NO_DB_CONNECTION",),
        )
        for tid in taxon_ids
    ]
