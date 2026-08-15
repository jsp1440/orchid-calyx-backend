"""KG-901A: read-only source-vs-graph coverage audit.

First bounded successor slice reconstructed from stale draft PR #901 (a
66-file, 148-commit branch never merged and treated as design source only,
per Orchid-Continuum-Brain issue #80's decomposition). This slice is
strictly READ-ONLY: it issues SELECT statements only, against the existing
verified `source_registry.py` queries and the persisted `oc_graph` tables,
and never writes to `oc_graph` or any other table. No materialization or
publication happens here - KG-901B (verified bulk source projections) and
later slices are separate, later work.

For each domain the registry has verified and enabled, measures:
  - raw_source_rows: total rows in the domain's raw source table/view.
  - exact_taxon_resolved_rows: rows the registry's own verified, taxon-node-
    joined query actually returns - i.e. rows that already carry a linkage
    to an existing `taxon` node in `oc_graph.kg_nodes` (per
    `SourceQuery.taxon_mapping`, `direct`/`resolved_view` joins are exact-id
    joins; `name_join` domains are scientific-name joins, the honest
    non-identifier fallback the registry itself documents).
  - persisted_graph_rows: rows currently persisted in `oc_graph.kg_nodes`/
    `kg_edges` whose `source_table` matches this domain's raw source table
    (confirmed by direct inspection of `adapters.py`'s node/edge specs to
    carry the identical literal string, not assumed).
  - coverage_pct: persisted_graph_rows / exact_taxon_resolved_rows, reported
    as 0.0 (not omitted) when there is nothing resolved to measure against.

Domains the registry has NOT verified (`source_registry.blocked_domains()`)
are reported separately, by name and reason only - this module makes no row-
count claim about them at all, rather than guessing at an unverified table.
"""

from __future__ import annotations

from typing import Any

from .source_registry import SOURCE_QUERIES, assert_safe_sql


def _count_rows(cur, sql: str) -> int:
    assert_safe_sql(sql)
    body = sql.strip().rstrip(";").strip()
    cur.execute(f"SELECT COUNT(*) FROM ({body}) AS resolved")
    return int(cur.fetchone()[0])


def _raw_table_row_count(cur, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


def _persisted_graph_row_count(cur, source_table: str) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM oc_graph.kg_nodes WHERE source_table = %s",
        (source_table,),
    )
    node_count = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(*) FROM oc_graph.kg_edges WHERE source_table = %s",
        (source_table,),
    )
    edge_count = int(cur.fetchone()[0])
    return node_count + edge_count


def source_vs_graph_coverage_audit(cur) -> dict[str, Any]:
    """Measure honest source-to-graph coverage for every registry-enabled
    domain. Issues SELECT statements only; never writes to `oc_graph` or
    any other table - no publication or materialization happens here."""

    domains: list[dict[str, Any]] = []
    for query in SOURCE_QUERIES:
        if not query.enabled or not query.sql:
            continue
        raw_table = query.expected_tables[0] if query.expected_tables else None
        raw_rows = _raw_table_row_count(cur, raw_table) if raw_table else None
        resolved_rows = _count_rows(cur, query.sql)
        graph_rows = _persisted_graph_row_count(cur, raw_table) if raw_table else 0
        coverage_pct = (graph_rows / resolved_rows) if resolved_rows else 0.0
        domains.append(
            {
                "domain": query.domain,
                "query_id": query.query_id,
                "taxon_mapping": query.taxon_mapping,
                "raw_source_table": raw_table,
                "raw_source_rows": raw_rows,
                "exact_taxon_resolved_rows": resolved_rows,
                "persisted_graph_rows": graph_rows,
                "coverage_pct": round(coverage_pct, 4),
                "missing_from_graph": max(resolved_rows - graph_rows, 0),
            }
        )

    blocked_domains = [
        {
            "domain": query.domain,
            "query_id": query.query_id,
            "blocked_reason": query.blocked_reason,
        }
        for query in SOURCE_QUERIES
        if not query.enabled
    ]

    return {
        "contract": "calyx-kg-901a-source-coverage-audit-v1",
        "graph_mutation": False,
        "domains": domains,
        "blocked_domains": blocked_domains,
    }
