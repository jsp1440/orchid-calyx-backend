"""Read-only inventory of scientific source corpora versus persisted graph coverage.

This module exists because a small number of graph nodes can conceal a much larger
relational corpus. It measures source tables and graph materialization side by
side without assuming that the first available telemetry table is the full corpus.

All relation names are fixed constants. The inventory performs SELECT-only
catalog/COUNT queries and never mutates production state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CorpusCandidate:
    domain: str
    relation: str
    graph_node_type: str | None = None
    graph_edge_type: str | None = None


# Includes legacy registry relations plus production relations discovered by the
# owner during the 2026-08-12 read-only PostgreSQL catalog inspection. Presence
# here makes a relation auditable; it does not make it publishable.
CANDIDATES: tuple[CorpusCandidate, ...] = (
    # Occurrence / geography / elevation corpus.
    CorpusCandidate("occurrences", "oc_atlas.occurrences", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "oc_atlas.map_data", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.occurrences", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.oc_occurrences", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.orchid_occurrence", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.orchid_occurrence_filtered", "occurrence", "occurs_at"),
    CorpusCandidate("occurrences", "public.records", "occurrence", "occurs_at"),
    CorpusCandidate("elevation", "public.v_records_elevation", "elevation", "has_elevation"),
    CorpusCandidate("elevation", "public.record_traits", "elevation", "has_elevation"),
    CorpusCandidate("elevation", "public.species_elevation_profile", "elevation", "has_elevation"),
    CorpusCandidate("elevation", "public.taxon_elevation_profile", "elevation", "has_elevation"),
    CorpusCandidate("elevation", "oc_env.taxon_elevation", "elevation", "has_elevation"),
    CorpusCandidate("elevation", "oc_dependency.elevation_derivation_queue", "elevation", "has_elevation"),

    # Trait corpus. Several live relations preserve evidence, source, geography,
    # elevation, consensus, and normalization rather than only flattened values.
    CorpusCandidate("traits", "oc_views.trait_resolved_v4", "trait", "has_trait"),
    CorpusCandidate("traits", "oc_traits.traits", "trait", "has_trait"),
    CorpusCandidate("traits", "public.oc_trait_consensus", "trait", "has_trait"),
    CorpusCandidate("traits", "public.oc_trait_consensus_normalized", "trait", "has_trait"),
    CorpusCandidate("traits", "public.oc_trait_knowledge", "trait", "has_trait"),
    CorpusCandidate("traits", "public.trait_assertions", "trait", "has_trait"),
    CorpusCandidate("traits", "public.trait_observations", "trait", "has_trait"),
    CorpusCandidate("traits", "public.traitbank_orchid_traits", "trait", "has_trait"),
    CorpusCandidate("traits", "public.traits", "trait", "has_trait"),
    CorpusCandidate("traits", "public.trait_elevation", "trait", "has_trait"),
    CorpusCandidate("traits", "public.trait_geography", "trait", "has_trait"),
    CorpusCandidate("traits", "public.trait_growth_habit", "trait", "has_trait"),

    # Literature and extracted scientific evidence corpus.
    CorpusCandidate("literature", "oc_literature.documents", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_literature.literature_documents", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_literature.papers", "publication", "documented_by"),
    CorpusCandidate("literature", "public.research_documents", "publication", "documented_by"),
    CorpusCandidate("literature", "public.trait_documents", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_citations.literature_nodes", "publication", "documented_by"),
    CorpusCandidate("literature", "oc_graph.taxon_literature_edges", "publication", "documented_by"),
    CorpusCandidate("evidence", "oc_claims.evidence_item", "evidence", "supported_by_evidence"),
    CorpusCandidate("evidence", "oc_claims.claim_evidence_link", "evidence", "supported_by_evidence"),
    CorpusCandidate("relationships", "oc_literature.extracted_relationships", "assertion", "supported_by_evidence"),

    # Ecology, habitat, interaction, fungal, pollinator and conservation corpus.
    CorpusCandidate("habitat", "oc_habitat.taxon_habitat", "habitat", "occupies_habitat"),
    CorpusCandidate("habitat", "oc_habitat.habitats", "habitat", "occupies_habitat"),
    CorpusCandidate("habitat", "public.oc_species_habitat_claims", "habitat", "occupies_habitat"),
    CorpusCandidate("relationships", "public.orchid_ecology_relationships", "assertion", "supported_by_evidence"),
    CorpusCandidate("pollinators", "oc_interactions.orchid_interaction_edges", "pollinator", "associated_with_pollinator"),
    CorpusCandidate("pollinators", "public.pollinators", "pollinator", "associated_with_pollinator"),
    CorpusCandidate("mycorrhiza", "oc_mycorrhiza.orchid_fungal_associations", "fungus", "associated_with_mycorrhiza"),
    CorpusCandidate("mycorrhiza", "public.orchid_fungus_associations", "fungus", "associated_with_mycorrhiza"),
    CorpusCandidate("conservation", "oc_conservation.conservation_records", "conservation_assessment", "has_conservation_assessment"),
)

SCIENTIFIC_COLUMN_HINTS: tuple[str, ...] = (
    "taxon_id",
    "taxonomy_id",
    "accepted_taxon_id",
    "species_id",
    "scientific_name",
    "scientific_name_raw",
    "country",
    "region",
    "locality",
    "latitude",
    "longitude",
    "decimal_latitude",
    "decimal_longitude",
    "elevation",
    "elevation_m",
    "elevation_meters",
    "minimum_elevation",
    "maximum_elevation",
    "elevation_min_m",
    "elevation_max_m",
    "trait_name",
    "trait_key",
    "trait_value",
    "trait_unit",
    "doi",
    "title",
    "abstract",
    "claim",
    "statement",
    "method",
    "result",
    "conclusion",
    "observation",
    "hypothesis",
    "evidence",
    "evidence_json",
    "citation",
    "reference",
    "habitat",
    "habitat_description",
    "interaction_type",
    "confidence",
    "confidence_score",
    "source",
    "source_id",
    "source_url",
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


def _graph_count(
    cur,
    *,
    node_type: str | None,
    edge_type: str | None,
) -> dict[str, int | None]:
    node_count: int | None = None
    edge_count: int | None = None
    if node_type:
        cur.execute(
            "SELECT COUNT(*) FROM oc_graph.kg_nodes WHERE node_type=%s",
            (node_type,),
        )
        node_count = int(cur.fetchone()[0])
    if edge_type:
        cur.execute(
            "SELECT COUNT(*) FROM oc_graph.kg_edges WHERE edge_type=%s",
            (edge_type,),
        )
        edge_count = int(cur.fetchone()[0])
    return {"graph_nodes": node_count, "graph_edges": edge_count}


def inventory_scientific_corpora(cur) -> dict[str, Any]:
    """Return source-vs-graph counts and relevant source columns."""
    rows: list[dict[str, Any]] = []
    graph_cache: dict[tuple[str | None, str | None], dict[str, int | None]] = {}
    hints = {hint.casefold() for hint in SCIENTIFIC_COLUMN_HINTS}
    for candidate in CANDIDATES:
        present = _relation_exists(cur, candidate.relation)
        item = asdict(candidate)
        item["present"] = present
        item["source_rows"] = _count(cur, candidate.relation) if present else None
        columns = _columns(cur, candidate.relation) if present else []
        item["scientific_columns"] = [
            name for name in columns if name.casefold() in hints
        ]
        key = (candidate.graph_node_type, candidate.graph_edge_type)
        if key not in graph_cache:
            graph_cache[key] = _graph_count(
                cur,
                node_type=candidate.graph_node_type,
                edge_type=candidate.graph_edge_type,
            )
        item.update(graph_cache[key])
        if (
            present
            and item["source_rows"] is not None
            and item["graph_nodes"] is not None
        ):
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
        "contract": "calyx-scientific-corpus-inventory-v2",
        "read_only": True,
        "graph_mutation": False,
        "candidate_presence_does_not_authorize_publication": True,
        "candidates": rows,
        "domains": by_domain,
    }
