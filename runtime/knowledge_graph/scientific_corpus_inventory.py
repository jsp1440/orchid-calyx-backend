"""Read-only inventory of scientific source corpora versus persisted graph coverage.

This module exists because a small number of graph nodes can conceal a much larger
relational corpus.  It measures source tables and graph materialization side by
side without assuming that the first available telemetry table is the full corpus.

All relation names are fixed constants.  The inventory performs SELECT-only
catalog/COUNT queries and never mutates production state.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class CorpusCandidate:
    domain: str
    relation: str
    graph_node_type: str | None = None
    graph_edge_type: str | None = None


CANDIDATES: tuple[CorpusCandidate, ...] = (
    CorpusCandidate("occurrences", "oc_atlas.occurrences", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "oc_atlas.map_data", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.occurrences", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.orchid_occurrences", "occurrence", "occurs_at"),
    CorpusCandidate("traits", "oc_views.trait_resolved_v4", "trait", "has_trait"),
    CorpusCandidate("traits", "oc_traits.traits", "trait", "has_trait"),
    CorpusCandidate("traits", "public.traitbank", "trait", "has_trait"),
    CorpusCandidate("traits", "public.traitbank_traits", "trait", "has_trait"),
    CorpusCandidate("literature", "oc_literature.documents", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_literature.literature_documents", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_literature.papers", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_citations.literature_nodes", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_graph.taxon_literature_edges", "publication", "documented_by"),
    CorpusCandidate("evidence", "oc_claims.evidence_item", "evidence", "supported_by_evidence"),
    CorpusCandidate("evidence", "oc_claims.claim_evidence_link", "evidence", "supported_by_evidence"),
    CorpusCandidate("relationships", "oc_literature.extracted_relationships", "assertion", "supported_by_evidence"),
    CorpusCandidate("habitat", "oc_habitat.taxon_habitat", "habitat", "occupies_habitat"),
    CorpusCandidate("habitat", "oc_habitat.habitats", "habitat", "occupies_habitat"),
    CorpusCandidate("elevation", "oc_env.taxon_elevation", "elevation", "has_elevation"),
    CorpusCandidate("elevation", "oc_dependency.elevation_derivation_queue", "elevation", "has_elevation"),
    CorpusCandidate("pollinators", "oc_interactions.orchid_interaction_edges", "pollinator", "associated_with_pollinator"),
    CorpusCandidate("mycorrhiza", "oc_mycorrhiza.orchid_fungal_associations", "fungus", "associated_with_mycorrhiza"),
    CorpusCandidate("conservation", "oc_conservation.conservation_records", "conservation_assessment", "has_conservation_assessment"),
)

SCIENTIFIC_COLUMN_HINTS: tuple[str, ...] = (
    "taxon_id", "taxonomy_id", "scientific_name", "country", "locality",
    "latitude", "longitude", "elevation", "minimum_elevation_m",
    "maximum_elevation_m", "trait_name", "trait_value", "doi", "title",
    "claim", "statement", "method", "result", "conclusion", "evidence",
    "citation", "reference", "habitat", "interaction_type",
)


def _relation_exists(cur, relation: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (relation,))
    row = cur.fetchone()
    return bool(row and row[0])


def _count(cur, relation: str) -> int:
    # Relation names come exclusively from CANDIDATES constants above.
    cur.execute(f"SELECT COUNT(*) FROM {relation}")
    return int(cur.fetchone()[0])


def _columns(cur, relation: str) -> list[str]:
    schema, table = relation.split(".", 1)
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return [str(row[0]) for row in cur.fetchall()]


def _graph_count(cur, *, node_type: str | None, edge_type: str | None) -> dict[str, int | None]:
    node_count: int | None = None
    edge_count: int | None = None
    if node_type:
        cur.execute("SELECT COUNT(*) FROM oc_graph.kg_nodes WHERE node_type=%s", (node_type,))
        node_count = int(cur.fetchone()[0])
    if edge_type:
        cur.execute("SELECT COUNT(*) FROM oc_graph.kg_edges WHERE edge_type=%s", (edge_type,))
        edge_count = int(cur.fetchone()[0])
    return {"graph_nodes": node_count, "graph_edges": edge_count}


def inventory_scientific_corpora(cur) -> dict[str, Any]:
    """Return source-vs-graph counts and relevant source columns."""
    rows: list[dict[str, Any]] = []
    graph_cache: dict[tuple[str | None, str | None], dict[str, int | None]] = {}
    for candidate in CANDIDATES:
        present = _relation_exists(cur, candidate.relation)
        item = asdict(candidate)
        item["present"] = present
        item["source_rows"] = _count(cur, candidate.relation) if present else None
        columns = _columns(cur, candidate.relation) if present else []
        item["scientific_columns"] = [
            name for name in columns if name.casefold() in {h.casefold() for h in SCIENTIFIC_COLUMN_HINTS}
        ]
        key = (candidate.graph_node_type, candidate.graph_edge_type)
        if key not in graph_cache:
            graph_cache[key] = _graph_count(
                cur,
                node_type=candidate.graph_node_type,
                edge_type=candidate.graph_edge_type,
            )
        item.update(graph_cache[key])
        if present and item["source_rows"] is not None and item["graph_nodes"] is not None:
            item["source_minus_graph_nodes"] = max(
                0, int(item["source_rows"]) - int(item["graph_nodes"])
            )
        else:
            item["source_minus_graph_nodes"] = None
        rows.append(item)

    by_domain: dict[str, dict[str, Any]] = {}
    for row in rows:
        domain = str(row["domain"])
        summary = by_domain.setdefault(
            domain,
            {
                "present_relations": 0,
                "max_source_rows": 0,
                "graph_nodes": row.get("graph_nodes"),
                "graph_edges": row.get("graph_edges"),
                "relations": [],
            },
        )
        if row["present"]:
            summary["present_relations"] += 1
            summary["max_source_rows"] = max(
                int(summary["max_source_rows"]), int(row["source_rows"] or 0)
            )
        summary["relations"].append(row["relation"])

    return {
        "contract": "calyx-scientific-corpus-inventory-v1",
        "read_only": True,
        "graph_mutation": False,
        "candidates": rows,
        "domains": by_domain,
    }
