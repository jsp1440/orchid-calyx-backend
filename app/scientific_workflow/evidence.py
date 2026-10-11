"""In-memory character-evidence store.

The store aggregates :class:`CharacterObservationRecord` values across sources
per taxon and exposes per-character :class:`CharacterStateView` objects:

* one source, one value            -> PRESENT / ABSENT view
* no source reports the character  -> UNKNOWN view (never fabricated)
* character cannot apply           -> INAPPLICABLE view
* sources disagree                 -> CONTRADICTORY view, every record kept

The store never writes anywhere; a production path would promote reviewed
records through the existing literature review workflow
(``app/literature_extraction/review.py``), not around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    CharacterObservationRecord,
    CharacterStateView,
    EvidenceKind,
    StateKind,
)


def _value_key(record: CharacterObservationRecord) -> Any:
    value = record.value
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return value


@dataclass
class CharacterEvidenceStore:
    """Append-only, query-by-taxon evidence store (offline, in-memory)."""

    _records: list[CharacterObservationRecord] | None = None

    def __post_init__(self) -> None:
        if self._records is None:
            self._records = []

    def add(self, records: Iterable[CharacterObservationRecord]) -> int:
        new = list(records)
        self._records.extend(new)
        return len(new)

    def records_for(
        self,
        taxon_id: str,
        *,
        character_id: str | None = None,
        evidence_kind: EvidenceKind | None = None,
    ) -> list[CharacterObservationRecord]:
        rows = [record for record in self._records if record.taxon_id == taxon_id]
        if character_id is not None:
            rows = [record for record in rows if record.character_id == character_id]
        if evidence_kind is not None:
            rows = [record for record in rows if record.evidence_kind == evidence_kind]
        return rows

    def taxa(self) -> list[str]:
        return sorted({record.taxon_id for record in self._records})

    def view(self, taxon_id: str, character_id: str) -> CharacterStateView:
        """Aggregate all records for one (taxon, character) pair.

        UNKNOWN records carry no scientific content; they are only used when
        nothing else exists.  INAPPLICABLE outranks UNKNOWN.  Conflicting
        PRESENT values across distinct sources produce CONTRADICTORY with the
        full disagreement visible.
        """

        records = self.records_for(taxon_id, character_id=character_id)
        substantive = [record for record in records if record.state_kind != StateKind.UNKNOWN]
        if not substantive:
            unknowns = [record for record in records if record.state_kind == StateKind.UNKNOWN]
            return CharacterStateView(
                taxon_id=taxon_id,
                character_id=character_id,
                state_kind=StateKind.UNKNOWN,
                value=None,
                unit_normalized=None,
                value_normalized=None,
                records=tuple(unknowns),
            )
        if any(record.state_kind == StateKind.INAPPLICABLE for record in substantive) and not any(
            record.state_kind in {StateKind.PRESENT, StateKind.ABSENT} for record in substantive
        ):
            return CharacterStateView(
                taxon_id=taxon_id,
                character_id=character_id,
                state_kind=StateKind.INAPPLICABLE,
                value=None,
                unit_normalized=None,
                value_normalized=None,
                records=tuple(substantive),
            )

        reported = [
            record
            for record in substantive
            if record.state_kind in {StateKind.PRESENT, StateKind.ABSENT}
        ]
        by_source: dict[str, CharacterObservationRecord] = {}
        for record in reported:
            # First record per source wins; a single source contradicting
            # itself is a curation issue, not a scientific disagreement.
            by_source.setdefault(record.source.source_id, record)
        distinct_values = {_value_key(record) for record in by_source.values()}
        distinct_kinds = {record.state_kind for record in by_source.values()}

        if len(by_source) > 1 and (len(distinct_values) > 1 or len(distinct_kinds) > 1):
            disagreement = tuple(
                {
                    "source_id": record.source.source_id,
                    "state_kind": str(record.state_kind),
                    "value": record.value,
                    "excerpt": record.span.excerpt if record.span else None,
                }
                for record in by_source.values()
            )
            return CharacterStateView(
                taxon_id=taxon_id,
                character_id=character_id,
                state_kind=StateKind.CONTRADICTORY,
                value=None,
                unit_normalized=None,
                value_normalized=None,
                records=tuple(by_source.values()),
                disagreement=disagreement,
            )

        chosen = reported[0]
        return CharacterStateView(
            taxon_id=taxon_id,
            character_id=character_id,
            state_kind=chosen.state_kind,
            value=chosen.value,
            unit_normalized=chosen.unit_normalized,
            value_normalized=chosen.value_normalized,
            records=tuple(by_source.values()),
        )

    def views_for_taxon(self, taxon_id: str, character_ids: Iterable[str]) -> list[CharacterStateView]:
        return [self.view(taxon_id, character_id) for character_id in character_ids]
