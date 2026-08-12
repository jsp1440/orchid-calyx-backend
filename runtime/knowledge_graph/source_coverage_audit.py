"""Read-only source-to-graph coverage measurements for critical scientific domains.

A graph edge type is not considered integrated merely because at least one edge
exists.  This audit measures authoritative source rows, rows resolving to the
canonical taxon backbone, and persisted graph materialization side by side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CoverageSpec:
    domain: str
    source_relation: str
    source_count_sql: str
    taxon_resolved_count_sql: str | None
    graph_node_type: str
    graph_edge_type: str


COVERAGE_SPECS: tuple[CoverageSpec, ...] = (
    CoverageSpec(
        domain="occurrences",
        source_relation="public.orchid_occurrence",
        source_count_sql="select count(*) from public.orchid_occurrence",
        taxon_resolved_count_sql="""
            select count(*)
            from public.orchid_occurrence o
            where o.taxonomy_id is not null
              and exists (
                  select 1 from oc_graph.kg_nodes k
                  where k.node_type='taxon'
                    and k.source_pk=o.taxonomy_id::text
              )
        """,
        graph_node_type="occurrence",
        graph_edge_type="occurs_at",
    ),
    CoverageSpec(
        domain="traits",
        source_relation="public.oc_trait_consensus_normalized",
        source_count_sql="select count(*) from public.oc_trait_consensus_normalized",
        taxon_resolved_count_sql="""
            select count(*)
            from public.oc_trait_consensus_normalized t
            where coalesce(t.accepted_taxon_id, t.taxon_id) is not null
              and t.normalized_trait_name is not null
              and exists (
                  select 1 from oc_graph.kg_nodes k
                  where k.node_type='taxon'
                    and k.source_pk=coalesce(t.accepted_taxon_id, t.taxon_id)::text
              )
        """,
        graph_node_type="trait",
        graph_edge_type="has_trait",
    ),
    CoverageSpec(
        domain="habitat",
        source_relation="public.oc_species_habitat_claims",
        source_count_sql="select count(*) from public.oc_species_habitat_claims",
        taxon_resolved_count_sql="""
            select count(*)
            from public.oc_species_habitat_claims h
            where h.taxonomy_id is not null
              and exists (
                  select 1 from oc_graph.kg_nodes k
                  where k.node_type='taxon'
                    and k.source_pk=h.taxonomy_id::text
              )
        """,
        graph_node_type="habitat",
        graph_edge_type="occupies_habitat",
    ),
    CoverageSpec(
        domain="literature",
        source_relation="public.research_documents",
        source_count_sql="select count(*) from public.research_documents",
        taxon_resolved_count_sql=None,
        graph_node_type="publication",
        graph_edge_type="documented_by",
    ),
)


def _scalar(cur, sql: str, params: tuple[Any, ...] = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def audit_source_coverage(cur) -> dict[str, Any]:
    """Measure authoritative source coverage without mutating any data."""
    domains: dict[str, Any] = {}
    for spec in COVERAGE_SPECS:
        source_rows = _scalar(cur, spec.source_count_sql)
        resolved_rows = (
            _scalar(cur, spec.taxon_resolved_count_sql)
            if spec.taxon_resolved_count_sql is not None
            else None
        )
        graph_nodes = _scalar(
            cur,
            "select count(*) from oc_graph.kg_nodes where node_type=%s",
            (spec.graph_node_type,),
        )
        graph_edges = _scalar(
            cur,
            "select count(*) from oc_graph.kg_edges where edge_type=%s",
            (spec.graph_edge_type,),
        )
        denominator = resolved_rows if resolved_rows is not None else source_rows
        domains[spec.domain] = {
            "source_relation": spec.source_relation,
            "source_rows": source_rows,
            "taxon_resolved_source_rows": resolved_rows,
            "graph_node_type": spec.graph_node_type,
            "graph_nodes": graph_nodes,
            "graph_edge_type": spec.graph_edge_type,
            "graph_edges": graph_edges,
            "node_coverage_of_resolved_source": _ratio(graph_nodes, denominator),
            "edge_coverage_of_resolved_source": _ratio(graph_edges, denominator),
            "source_minus_graph_edges": max(0, denominator - graph_edges),
            "taxon_crosswalk_required": resolved_rows is not None,
        }

    return {
        "contract": "calyx-source-coverage-audit-v1",
        "read_only": True,
        "graph_mutation": False,
        "domains": domains,
    }
