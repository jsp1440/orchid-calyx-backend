"""Offline Lexicon terminology service.

This is the fixture-backed sibling of the live Lexicon facade in
``app/lexicon/routes.py``.  The live facade serves ACTIVE + APPROVED concepts
from the ``oc_concepts`` registry; this service serves a curated CSV fixture
with the *same payload shape* (preferred label, synonyms, definition, review
state) so the terminology normalisation path can be exercised deterministically
and so the same code can later be bound to the registry without changing its
callers.

External accession mappings reuse the curated OAO resolution table produced in
Orchid-Continuum-Brain draft PR #230 (branch ``discovery/oao-accession-resolution``,
every accession verified against the EBI OLS4 API on 2026-10-10).  Rows marked
``extension_required`` or ``rejected`` are preserved: they are explicit
negative evidence, not gaps to be filled by guessing.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AccessionMapping:
    role: str  # entity | quality | state
    candidate_key: str
    accession: str | None
    label: str | None
    ontology: str | None
    relation: str
    status: str  # resolved_curated | review_required | extension_required | rejected | not_applicable

    @property
    def is_usable(self) -> bool:
        return self.status == "resolved_curated" and bool(self.accession)


@dataclass(frozen=True)
class LexiconTerm:
    term_id: str
    canonical_term: str
    synonyms: tuple[str, ...]
    category: str
    definition: str
    definition_source: str
    example_taxa: tuple[str, ...]
    review_state: str = "APPROVED"

    @property
    def slug(self) -> str:
        return slugify(self.canonical_term)

    def all_labels(self) -> tuple[str, ...]:
        return (self.canonical_term, *self.synonyms)


@dataclass(frozen=True)
class TermMatch:
    term: LexiconTerm
    matched_label: str
    start: int
    end: int


def slugify(value: str) -> str:
    """Same normalisation rule as ``app.lexicon.routes._slug``."""

    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9×]+", "-", value)
    return value.strip("-")


def _split_multi(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(";") if part.strip())


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(
            row for row in handle if not row.lstrip().startswith("#") and row.strip()
        )
        return [dict(row) for row in reader]


class TerminologyService(Protocol):
    def get(self, term_id: str) -> LexiconTerm | None: ...
    def match_text(self, text: str) -> list[TermMatch]: ...
    def accessions_for(self, term_id: str) -> list[AccessionMapping]: ...
    def terms(self) -> list[LexiconTerm]: ...


class CuratedTerminologyService:
    """CSV-fixture terminology service with OAO accession cross-references."""

    # Maps lexicon term ids to the OAO curated-table entity candidate keys.
    # Keys are the exact ``candidate_key`` strings of the Brain PR #230 table.
    ENTITY_KEYS: dict[str, str] = {
        "labellum": "labellum",
        "pseudobulb": "pseudobulb",
        "pollinium": "pollinium",
        "rostellum": "rostellum",
        "viscidium": "viscidium",
        "velamen": "velamen",
        "floral_spur": "floral spur / nectary",
        "gynostemium": "gynostemium / column",
    }

    def __init__(self, terms_csv: Path, oao_accessions_csv: Path) -> None:
        self._terms: dict[str, LexiconTerm] = {}
        for row in _rows(terms_csv):
            term = LexiconTerm(
                term_id=row["term_id"].strip(),
                canonical_term=row["canonical_term"].strip(),
                synonyms=_split_multi(row.get("synonyms", "")),
                category=row["category"].strip(),
                definition=row["definition"].strip(),
                definition_source=row["definition_source"].strip(),
                example_taxa=_split_multi(row.get("example_taxa", "")),
                review_state=(row.get("review_state") or "APPROVED").strip(),
            )
            self._terms[term.term_id] = term
        self._accessions: list[AccessionMapping] = []
        for row in _rows(oao_accessions_csv):
            self._accessions.append(
                AccessionMapping(
                    role=row["role"].strip(),
                    candidate_key=row["candidate_key"].strip(),
                    accession=(row.get("accession") or "").strip() or None,
                    label=(row.get("label") or "").strip() or None,
                    ontology=(row.get("ontology") or "").strip() or None,
                    relation=(row.get("relation") or "").strip(),
                    status=(row.get("status") or "").strip(),
                )
            )
        self._patterns: list[tuple[LexiconTerm, str, re.Pattern[str]]] = []
        for term in self._terms.values():
            for label in term.all_labels():
                pattern = re.compile(rf"\b{re.escape(label)}\b", re.IGNORECASE)
                self._patterns.append((term, label, pattern))

    def get(self, term_id: str) -> LexiconTerm | None:
        return self._terms.get(term_id)

    def terms(self) -> list[LexiconTerm]:
        return sorted(self._terms.values(), key=lambda term: term.term_id)

    def match_text(self, text: str) -> list[TermMatch]:
        """Match lexicon labels in *text*; longest label wins on overlap."""

        matches: list[TermMatch] = []
        for term, label, pattern in self._patterns:
            for hit in pattern.finditer(text):
                matches.append(
                    TermMatch(term=term, matched_label=hit.group(0), start=hit.start(), end=hit.end())
                )
        matches.sort(key=lambda item: (item.start, -(item.end - item.start)))
        kept: list[TermMatch] = []
        covered: list[tuple[int, int]] = []
        for match in matches:
            if any(start <= match.start < end for start, end in covered):
                continue
            covered.append((match.start, match.end))
            kept.append(match)
        return kept

    def accessions_for(self, term_id: str, *, include_rejected: bool = True) -> list[AccessionMapping]:
        """Curated external accessions for a term's OAO entity key.

        Rejected and extension-required rows stay visible by default because
        they document verified negative evidence (e.g. there is no PO class
        for pollinium; BTO labellum is animal anatomy and must not be reused).
        """

        key = self.ENTITY_KEYS.get(term_id)
        if key is None:
            return []
        rows = [row for row in self._accessions if row.role == "entity" and row.candidate_key == key]
        if not include_rejected:
            rows = [row for row in rows if row.status not in {"rejected"}]
        return rows

    def quality_accessions(self, *quality_keys: str) -> list[AccessionMapping]:
        wanted = set(quality_keys)
        return [row for row in self._accessions if row.role == "quality" and row.candidate_key in wanted]

    def state_accession(self, state_label: str) -> AccessionMapping | None:
        needle = state_label.casefold().strip()
        for row in self._accessions:
            if row.role == "state" and row.candidate_key.casefold() == needle:
                return row
        return None

    def entry_payload(self, term_id: str) -> dict[str, Any] | None:
        """Lexicon-facade-shaped payload for one term (offline equivalent of
        ``GET /api/lexicon/entries/{slug}``)."""

        term = self.get(term_id)
        if term is None:
            return None
        accessions = [row.__dict__ for row in self.accessions_for(term_id)]
        return {
            "id": term.term_id,
            "concept_id": term.term_id,
            "slug": term.slug,
            "preferred_term": term.canonical_term,
            "expanded_definition": term.definition,
            "synonyms": list(term.synonyms),
            "category": term.category,
            "review_state": term.review_state.casefold(),
            "example_taxa": list(term.example_taxa),
            "external_accessions": accessions,
            "provenance": {
                "source": "Curated Orchid Continuum lexicon fixture",
                "definition_source": term.definition_source,
                "accession_source": (
                    "Orchid-Continuum-Brain draft PR #230 curated OAO resolution "
                    "table (OLS4-verified 2026-10-10)"
                ),
                "validation_status": term.review_state.casefold(),
            },
        }
