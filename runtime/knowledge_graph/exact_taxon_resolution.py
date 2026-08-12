"""Exact taxon resolution for literature-derived graph projections.

This resolver is intentionally narrow. It accepts extracted taxon entities from
``PaperKnowledge`` and resolves only exact case-insensitive matches against active
persisted ``taxon`` node display labels. Ambiguous matches fail closed. No fuzzy
matching, synonym guessing, taxonomy creation, or graph mutation occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from app.literature_extraction.models import PaperKnowledge


@dataclass(frozen=True, slots=True)
class ExactTaxonResolution:
    keys_by_entity_id: dict[str, str]
    unresolved_entity_ids: tuple[str, ...]
    ambiguous_entity_ids: tuple[str, ...]

    @property
    def resolved_count(self) -> int:
        return len(self.keys_by_entity_id)


def _resolve_with_cursor(cur, paper: PaperKnowledge) -> ExactTaxonResolution:
    keys: dict[str, str] = {}
    unresolved: list[str] = []
    ambiguous: list[str] = []

    for entity in paper.entities:
        if entity.entity_type != "taxon":
            continue
        name = str(entity.normalized_name or entity.name or "").strip()
        if not name:
            unresolved.append(entity.entity_id)
            continue
        cur.execute(
            """
            SELECT canonical_key
            FROM oc_graph.kg_nodes
            WHERE node_type = 'taxon'
              AND is_active
              AND lower(display_label) = lower(%s)
            ORDER BY kg_node_id
            LIMIT 2
            """,
            (name,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            keys[entity.entity_id] = str(rows[0][0])
        elif len(rows) > 1:
            ambiguous.append(entity.entity_id)
        else:
            unresolved.append(entity.entity_id)

    return ExactTaxonResolution(
        keys_by_entity_id=keys,
        unresolved_entity_ids=tuple(unresolved),
        ambiguous_entity_ids=tuple(ambiguous),
    )


def resolve_exact_taxon_keys_for_paper(
    dsn: str,
    paper: PaperKnowledge,
) -> ExactTaxonResolution:
    """Resolve extracted taxon entities against active persisted graph taxa."""
    if not str(dsn or "").strip():
        raise ValueError("DATABASE_URL_REQUIRED")
    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        conn.read_only = True
        return _resolve_with_cursor(cur, paper)
