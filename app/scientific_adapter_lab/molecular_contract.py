"""Governed, provider-free molecular accession contract.

This module is intentionally read-only. It models reviewed molecular evidence without
calling external sequence services, mutating taxonomy, or publishing scientific claims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Protocol


class SequenceBindingState(str, Enum):
    ACCESSION_VERIFIED = "accession_verified"
    TAXON_UNRESOLVED = "taxon_unresolved"
    FUNGUS_UNRESOLVED = "fungus_unresolved"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SequenceRecord:
    taxon_name: str
    taxon_kind: str
    accession_id: str | None
    locus: str
    source_authority: str
    tissue_type: str | None
    life_stage: str | None
    binding_state: SequenceBindingState
    method: str
    reviewed_taxon: bool = False
    accession_verified: bool = False
    unpublished: bool = False

    def __post_init__(self) -> None:
        if self.binding_state is SequenceBindingState.ACCESSION_VERIFIED:
            if not self.accession_id or not self.accession_verified:
                raise ValueError("verified binding requires a verified accession id")
        if self.binding_state is SequenceBindingState.CONFLICT and self.accession_verified:
            raise ValueError("conflicting evidence cannot be promoted as verified")

    def to_public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["binding_state"] = self.binding_state.value
        if self.unpublished:
            payload["accession_id"] = None
            payload["binding_state"] = SequenceBindingState.UNKNOWN.value
        return payload


class MolecularRepository(Protocol):
    def records_for_taxon(self, taxon_name: str) -> Iterable[SequenceRecord]:
        ...


@dataclass(frozen=True)
class MolecularMatrix:
    taxon_name: str
    state: SequenceBindingState
    records: tuple[SequenceRecord, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "taxon_name": self.taxon_name,
            "state": self.state.value,
            "records": [record.to_public_dict() for record in self.records],
        }


def build_unavailable_molecular_matrix(taxon_name: str) -> MolecularMatrix:
    return MolecularMatrix(
        taxon_name=taxon_name,
        state=SequenceBindingState.UNKNOWN,
        records=(),
    )


def _precedence(record: SequenceRecord) -> tuple[int, int]:
    return (
        1 if record.accession_verified else 0,
        1 if record.reviewed_taxon else 0,
    )


class MolecularGateway:
    """Read-through facade that fails closed when molecular storage is absent."""

    def __init__(self, repository: MolecularRepository | None = None) -> None:
        self._repository = repository

    def read_taxon(self, taxon_name: str) -> MolecularMatrix:
        if self._repository is None:
            return build_unavailable_molecular_matrix(taxon_name)

        records = tuple(self._repository.records_for_taxon(taxon_name))
        if not records:
            return build_unavailable_molecular_matrix(taxon_name)

        ordered = tuple(sorted(records, key=_precedence, reverse=True))
        if any(r.binding_state is SequenceBindingState.CONFLICT for r in ordered):
            state = SequenceBindingState.CONFLICT
        else:
            state = ordered[0].binding_state
        return MolecularMatrix(taxon_name=taxon_name, state=state, records=ordered)
