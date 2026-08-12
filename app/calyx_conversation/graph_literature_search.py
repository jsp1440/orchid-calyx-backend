"""Read-only lexical search over persisted Knowledge Graph literature nodes.

This is a governed fallback for the case where the semantic evidence index is
empty/degraded but literature has already been materialized into ``oc_graph``.
It does not replace the semantic index and does not infer scientific claims.
Returned records are persisted graph nodes plus their taxon-link provenance.
"""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg

MAX_QUERY_TERMS = 6
MAX_RESULTS = 8
_STOPWORDS = {
    "about", "after", "again", "also", "among", "and", "answer", "been",
    "before", "between", "could", "does", "from", "have", "into", "known",
    "literature", "orchid", "orchids", "plant", "plants", "question", "say",
    "show", "study", "studies", "their", "there", "these", "they", "this",
    "those", "through", "using", "what", "when", "where", "which", "with",
    "would", "your",
}


def lexical_terms(message: str) -> tuple[str, ...]:
    """Return bounded scientific search terms without expanding synonyms."""
    tokens = re.findall(r"[A-Za-z][A-Za-z-]{3,}", str(message or "").casefold())
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.strip("-")
        if len(token) < 4 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= MAX_QUERY_TERMS:
            break
    return tuple(result)


def _search_sql(term_count: int) -> str:
    predicates = []
    for _ in range(term_count):
        predicates.append(
            "(lower(coalesce(p.display_label,'')) LIKE %s "
            "OR lower(coalesce(p.payload_json::text,'')) LIKE %s)"
        )
    where = " OR ".join(predicates)
    return f"""
        SELECT p.kg_node_id, p.display_label, p.source_table, p.source_pk,
               p.evidence_class, p.confidence_score, p.confidence_label,
               p.payload_json
        FROM oc_graph.kg_nodes p
        WHERE p.node_type = 'publication' AND p.is_active
          AND ({where})
        ORDER BY p.confidence_score DESC NULLS LAST, p.kg_node_id
        LIMIT %s
    """


def search_persisted_literature(
    message: str,
    *,
    dsn: str | None = None,
    limit: int = MAX_RESULTS,
) -> dict[str, Any]:
    """Search publication nodes and return taxon-link provenance, read-only."""
    terms = lexical_terms(message)
    if not terms:
        return {
            "status": "not_requested",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "terms": [],
            "results": [],
        }
    resolved_dsn = (dsn or os.getenv("DATABASE_URL") or "").strip()
    if not resolved_dsn:
        return {
            "status": "unavailable",
            "reason": "DATABASE_URL_NOT_CONFIGURED",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "terms": list(terms),
            "results": [],
        }
    resolved_limit = max(1, min(int(limit), MAX_RESULTS))
    params: list[Any] = []
    for term in terms:
        pattern = f"%{term}%"
        params.extend((pattern, pattern))
    params.append(resolved_limit)

    try:
        with psycopg.connect(resolved_dsn, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(_search_sql(len(terms)), tuple(params))
            rows = cur.fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                node_id = int(row[0])
                cur.execute(
                    """
                    SELECT DISTINCT t.display_label
                    FROM oc_graph.kg_edges e
                    JOIN oc_graph.kg_nodes t ON t.kg_node_id = e.from_node_id
                    WHERE e.to_node_id = %s
                      AND e.edge_type = 'documented_by'
                      AND e.is_active
                      AND t.node_type = 'taxon'
                      AND t.is_active
                    ORDER BY t.display_label
                    LIMIT 12
                    """,
                    (node_id,),
                )
                taxa = [str(item[0]) for item in cur.fetchall()]
                payload = dict(row[7] or {}) if isinstance(row[7], dict) else {}
                results.append(
                    {
                        "kg_node_id": node_id,
                        "title": row[1],
                        "source_table": row[2],
                        "source_pk": row[3],
                        "evidence_class": row[4],
                        "confidence_score": row[5],
                        "confidence_label": row[6],
                        "doi": payload.get("doi"),
                        "year": payload.get("year"),
                        "edge_strength": payload.get("edge_strength"),
                        "associated_taxa": taxa,
                        "provenance": {
                            "graph_node_type": "publication",
                            "relationship": "documented_by",
                            "payload_source": "oc_graph.kg_nodes.payload_json",
                        },
                    }
                )
    except psycopg.Error as exc:
        return {
            "status": "unavailable",
            "reason": f"GRAPH_LITERATURE_READ_FAILED:{exc.__class__.__name__}",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "terms": list(terms),
            "results": [],
        }

    return {
        "status": "available",
        "read_only": True,
        "knowledge_graph_mutation": False,
        "search_policy": "literal_terms_no_synonym_expansion",
        "terms": list(terms),
        "result_count": len(results),
        "results": results,
    }
