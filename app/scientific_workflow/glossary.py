"""Illustrated Glossary assembly.

Builds retrieval-ready glossary entries from the terminology service plus an
illustration registry.  Honesty rules enforced here:

* ``status == "needs_illustration"`` is a first-class, visible state.  An entry
  without a permitted image says so; no image is ever fabricated or implied.
* Illustrations carry their class (e.g. Class D conceptual diagram, per the
  Famous/Continuum validation scheme), license and attribution.  A conceptual
  schematic is never presented as specimen evidence.
* Entries cross-link to Matrix characters that use the term and to species
  dossiers via example taxa.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .terminology import TerminologyService, _rows


@dataclass(frozen=True)
class IllustrationRecord:
    term_id: str
    status: str  # available | needs_illustration
    asset_ref: str | None
    illustration_class: str | None
    license: str | None
    attribution: str | None
    notes: str | None

    @property
    def available(self) -> bool:
        return self.status == "available" and bool(self.asset_ref)


class IllustrationRegistry:
    """CSV-backed registry of permitted illustration records."""

    def __init__(self, illustrations_csv: Path) -> None:
        self._by_term: dict[str, IllustrationRecord] = {}
        for row in _rows(illustrations_csv):
            record = IllustrationRecord(
                term_id=row["term_id"].strip(),
                status=(row.get("status") or "needs_illustration").strip(),
                asset_ref=(row.get("asset_ref") or "").strip() or None,
                illustration_class=(row.get("illustration_class") or "").strip() or None,
                license=(row.get("license") or "").strip() or None,
                attribution=(row.get("attribution") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
            )
            self._by_term[record.term_id] = record

    def for_term(self, term_id: str) -> IllustrationRecord:
        return self._by_term.get(
            term_id,
            IllustrationRecord(
                term_id=term_id,
                status="needs_illustration",
                asset_ref=None,
                illustration_class=None,
                license=None,
                attribution=None,
                notes="No illustration record exists for this term.",
            ),
        )


def build_glossary_entry(
    term_id: str,
    terminology: TerminologyService,
    illustrations: IllustrationRegistry,
    *,
    matrix_character_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Assemble one Illustrated Glossary entry (retrieval payload).

    Returns ``None`` when the term is unknown to the lexicon — unknown terms
    are never given fabricated entries.
    """

    entry = terminology.entry_payload(term_id)
    if entry is None:
        return None
    illustration = illustrations.for_term(term_id)
    entry["illustration"] = {
        "status": illustration.status,
        "needs_illustration": not illustration.available,
        "asset_ref": illustration.asset_ref,
        "illustration_class": illustration.illustration_class,
        "license": illustration.license,
        "attribution": illustration.attribution,
        "notes": illustration.notes,
        "fabricated": False,
        "specimen_evidence": False,
    }
    entry["cross_links"] = {
        "matrix_characters": matrix_character_ids or [],
        "species_dossiers": [
            {"example_taxon": taxon} for taxon in entry.get("example_taxa", [])
        ],
    }
    return entry


def build_glossary_index(
    terminology: TerminologyService,
    illustrations: IllustrationRegistry,
) -> dict[str, Any]:
    """Glossary retrieval index: every lexicon term with its illustration state."""

    entries = []
    for term in terminology.terms():
        record = illustrations.for_term(term.term_id)
        entries.append(
            {
                "term_id": term.term_id,
                "slug": term.slug,
                "preferred_term": term.canonical_term,
                "category": term.category,
                "illustration_status": record.status,
                "needs_illustration": not record.available,
            }
        )
    return {
        "count": len(entries),
        "entries": entries,
        "illustration_coverage": {
            "available": sum(1 for item in entries if not item["needs_illustration"]),
            "needs_illustration": sum(1 for item in entries if item["needs_illustration"]),
        },
        "policy": {
            "fabricated_images_prohibited": True,
            "conceptual_schematics_are_not_specimen_evidence": True,
            "missing_illustrations_are_shown_as_missing": True,
        },
    }
