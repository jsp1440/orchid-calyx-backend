"""Read-only literature retrieval across persisted graph and research documents.

The primary path searches persisted ``publication`` nodes and their taxon-link
provenance. Because the live audit proved that the graph currently represents
only a small subset of the 6,725-document research corpus, an exact-binomial
fallback also searches ``public.research_documents`` for literal taxon mentions.
Where a corpus document has a canonical literature-extraction binding, the result
is enriched with integrity-verified, publication-eligible normalized evidence.
No literal mention is promoted into a scientific claim or persisted graph edge.
"""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg

from .extracted_literature_evidence import reviewed_evidence_for_documents
from .graph_context import explicit_taxon_names

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


def _research_document_matches(
    cur,
    taxon_names: tuple[str, ...],
    *,
    limit: int,
    seen_source_keys: set[str],
) -> list[dict[str, Any]]:
    """Return literal exact-binomial document matches from the bulk corpus."""
    if not taxon_names or limit < 1:
        return []
    predicates: list[str] = []
    params: list[Any] = []
    for name in taxon_names:
        pattern = f"%{name.casefold()}%"
        predicates.append(
            "(lower(coalesce(d.title,'')) like %s "
            "or lower(coalesce(d.abstract,'')) like %s "
            "or lower(coalesce(d.keywords::text,'')) like %s)"
        )
        params.extend((pattern, pattern, pattern))
    params.append(limit)
    cur.execute(
        f"""
        SELECT d.id, d.title, d.doi, d.year, d.document_type,
               d.abstract, d.keywords
        FROM public.research_documents d
        WHERE coalesce(d.is_searchable, true)
          AND ({' OR '.join(predicates)})
        ORDER BY d.citation_count DESC NULLS LAST, d.year DESC NULLS LAST, d.id
        LIMIT %s
        """,
        tuple(params),
    )
    results: list[dict[str, Any]] = []
    for row in cur.fetchall():
        source_key = f"public.research_documents:{row[0]}"
        if source_key in seen_source_keys:
            continue
        blob = " ".join(str(value or "") for value in (row[1], row[5], row[6])).casefold()
        matched_taxa = [name for name in taxon_names if name.casefold() in blob]
        if not matched_taxa:
            continue
        results.append(
            {
                "kg_node_id": None,
                "title": row[1],
                "source_table": "public.research_documents",
                "source_pk": str(row[0]),
                "evidence_class": "research_document_metadata",
                "confidence_score": None,
                "confidence_label": "literal_taxon_mention",
                "doi": row[2],
                "year": row[3],
                "document_type": row[4],
                "associated_taxa": matched_taxa,
                "reviewed_evidence": [],
                "provenance": {
                    "graph_node_type": None,
                    "relationship": "literal_binomial_mention",
                    "payload_source": "public.research_documents",
                    "persisted_graph_edge": False,
                    "scientific_claim_inferred": False,
                },
            }
        )
    return results


def _attach_reviewed_evidence(results: list[dict[str, Any]]) -> dict[str, Any]:
    document_ids = [
        item.get("source_pk")
        for item in results
        if item.get("source_table") == "public.research_documents"
    ]
    bridge = reviewed_evidence_for_documents(document_ids)
    documents = bridge.get("documents") or {}
    for item in results:
        if item.get("source_table") != "public.research_documents":
            continue
        document = documents.get(str(item.get("source_pk"))) or {}
        records = list(document.get("records") or [])
        item["reviewed_evidence"] = records
        item["extraction_evidence_status"] = document.get("status")
        item["provenance"]["reviewed_extraction_binding"] = bool(
            document.get("bindings")
        )
        item["provenance"]["publication_eligible_evidence"] = bool(records)
    return bridge


def search_persisted_literature(
    message: str,
    *,
    dsn: str | None = None,
    limit: int = MAX_RESULTS,
) -> dict[str, Any]:
    """Search graph publications plus exact-taxon bulk documents, read-only."""
    terms = lexical_terms(message)
    taxon_names = explicit_taxon_names(message)
    if not terms and not taxon_names:
        return {
            "status": "not_requested",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "terms": [],
            "explicit_taxa": [],
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
            "explicit_taxa": list(taxon_names),
            "results": [],
        }
    resolved_limit = max(1, min(int(limit), MAX_RESULTS))

    try:
        with psycopg.connect(resolved_dsn, connect_timeout=5) as conn, conn.cursor() as cur:
            conn.read_only = True
            results: list[dict[str, Any]] = []
            seen_source_keys: set[str] = set()
            if terms:
                params: list[Any] = []
                for term in terms:
                    pattern = f"%{term}%"
                    params.extend((pattern, pattern))
                params.append(resolved_limit)
                cur.execute(_search_sql(len(terms)), tuple(params))
                for row in cur.fetchall():
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
                    source_key = f"{row[2]}:{row[3]}"
                    seen_source_keys.add(source_key)
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
                            "reviewed_evidence": [],
                            "provenance": {
                                "graph_node_type": "publication",
                                "relationship": "documented_by",
                                "payload_source": "oc_graph.kg_nodes.payload_json",
                                "persisted_graph_edge": True,
                            },
                        }
                    )
            remaining = resolved_limit - len(results)
            if remaining > 0 and taxon_names:
                results.extend(
                    _research_document_matches(
                        cur,
                        taxon_names,
                        limit=remaining,
                        seen_source_keys=seen_source_keys,
                    )
                )
    except psycopg.Error as exc:
        return {
            "status": "unavailable",
            "reason": f"GRAPH_LITERATURE_READ_FAILED:{exc.__class__.__name__}",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "terms": list(terms),
            "explicit_taxa": list(taxon_names),
            "results": [],
        }

    bridge = _attach_reviewed_evidence(results)
    graph_count = sum(bool(item.get("kg_node_id")) for item in results)
    document_count = len(results) - graph_count
    reviewed_count = sum(len(item.get("reviewed_evidence") or []) for item in results)
    return {
        "status": "available",
        "read_only": True,
        "knowledge_graph_mutation": False,
        "search_policy": "graph_literal_terms_plus_exact_binomial_document_fallback",
        "terms": list(terms),
        "explicit_taxa": list(taxon_names),
        "result_count": len(results),
        "persisted_graph_results": graph_count,
        "research_document_fallback_results": document_count,
        "publication_eligible_evidence_records": reviewed_count,
        "extraction_evidence_bridge": {
            "status": bridge.get("status"),
            "reviewed_record_count": bridge.get("reviewed_record_count", 0),
            "automatic_publication": False,
        },
        "results": results,
    }
