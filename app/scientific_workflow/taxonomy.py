"""Offline taxon resolution.

Reuses the name-normalisation rule already shipping in
``app.species_dossier.service.normalize_scientific_name`` so the workflow and
the federation gateway agree on what "the same name" means.  The fixture
resolver below is the deterministic stand-in for the governed live sources
(World Plants intake under ``runtime/world_plants_*``, POWO/IPNI federation
partners): live resolution is *not* attempted inside tests, and an unresolved
name is reported as unresolved rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.species_dossier.service import normalize_scientific_name

from .terminology import _rows


@dataclass(frozen=True)
class TaxonRecord:
    taxon_id: str
    accepted_name: str
    authorship: str
    family: str
    synonyms: tuple[str, ...]

    @property
    def full_scientific_name(self) -> str:
        return f"{self.accepted_name} {self.authorship}".strip()

    @property
    def genus(self) -> str:
        return self.accepted_name.split()[0]

    @property
    def specific_epithet(self) -> str | None:
        parts = self.accepted_name.split()
        return parts[1] if len(parts) > 1 else None


@dataclass(frozen=True)
class TaxonResolution:
    status: Literal["resolved", "unresolved", "ambiguous"]
    incoming_name: str
    match_state: Literal["accepted_name", "synonym", "none"]
    taxon: TaxonRecord | None
    explanation: str
    resolver: str
    resolver_version: str


class TaxonResolver(Protocol):
    def resolve(self, name: str) -> TaxonResolution: ...


class FixtureTaxonResolver:
    """Resolves names against the curated taxa fixture (no live calls)."""

    VERSION = "fixture-taxon-resolver-001"

    def __init__(self, taxa_csv: Path) -> None:
        self._by_normalized: dict[str, tuple[TaxonRecord, str]] = {}
        for row in _rows(taxa_csv):
            record = TaxonRecord(
                taxon_id=row["taxon_id"].strip(),
                accepted_name=row["accepted_name"].strip(),
                authorship=row["authorship"].strip(),
                family=row["family"].strip(),
                synonyms=tuple(
                    part.strip() for part in (row.get("synonyms") or "").split(";") if part.strip()
                ),
            )
            accepted_key = normalize_scientific_name(record.accepted_name)
            if accepted_key:
                self._by_normalized[accepted_key] = (record, "accepted_name")
            for synonym in record.synonyms:
                key = normalize_scientific_name(synonym)
                if key:
                    self._by_normalized.setdefault(key, (record, "synonym"))

    def resolve(self, name: str) -> TaxonResolution:
        key = normalize_scientific_name(name or "")
        if key is None:
            return TaxonResolution(
                status="unresolved",
                incoming_name=name,
                match_state="none",
                taxon=None,
                explanation="Name could not be normalised to a binomial; no resolution attempted.",
                resolver="fixture",
                resolver_version=self.VERSION,
            )
        hit = self._by_normalized.get(key)
        if hit is None:
            return TaxonResolution(
                status="unresolved",
                incoming_name=name,
                match_state="none",
                taxon=None,
                explanation=(
                    "Name is not present in the curated taxon fixture and no live "
                    "resolver is configured for this run; the name is left unresolved "
                    "rather than guessed."
                ),
                resolver="fixture",
                resolver_version=self.VERSION,
            )
        record, match_state = hit
        return TaxonResolution(
            status="resolved",
            incoming_name=name,
            match_state=match_state,  # type: ignore[arg-type]
            taxon=record,
            explanation=f"Resolved via curated fixture by {match_state.replace('_', ' ')}.",
            resolver="fixture",
            resolver_version=self.VERSION,
        )
