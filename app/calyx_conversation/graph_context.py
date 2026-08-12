"""Read-only persisted Knowledge Graph context for scientific Speak turns.

The bridge is intentionally conservative: it extracts only explicit binomial
names from the current user message, resolves them by exact taxon display label,
and traverses the persisted graph. It never performs fuzzy identification and
never mutates graph state.
"""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg

from runtime.knowledge_graph import PostgresGraphRepository, traverse

_BINOMIAL = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z][a-z-]{2,})\b")
MAX_TAXA_PER_TURN = 3


def explicit_taxon_names(message: str) -> tuple[str, ...]:
    """Return de-duplicated explicit binomials; no fuzzy/common-name inference."""
    names: list[str] = []
    seen: set[str] = set()
    for match in _BINOMIAL.finditer(str(message or "")):
        name = f"{match.group(1)} {match.group(2)}"
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= MAX_TAXA_PER_TURN:
            break
    return tuple(names)


def _resolve_taxon_node_id(dsn: str, scientific_name: str) -> int | None:
    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT kg_node_id
            FROM oc_graph.kg_nodes
            WHERE node_type = 'taxon'
              AND is_active
              AND lower(display_label) = lower(%s)
            ORDER BY kg_node_id
            LIMIT 1
            """,
            (scientific_name,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def graph_context_for_message(
    message: str,
    *,
    dsn: str | None = None,
    depth: int = 1,
    limit: int = 80,
) -> dict[str, Any]:
    """Resolve explicit taxa and return bounded persisted graph traversals."""
    names = explicit_taxon_names(message)
    if not names:
        return {
            "status": "not_requested",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "requested_taxa": [],
            "taxa": [],
        }

    resolved_dsn = (dsn or os.getenv("DATABASE_URL") or "").strip()
    if not resolved_dsn:
        return {
            "status": "unavailable",
            "reason": "DATABASE_URL_NOT_CONFIGURED",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "requested_taxa": list(names),
            "taxa": [],
        }

    repo = PostgresGraphRepository(resolved_dsn)
    taxa: list[dict[str, Any]] = []
    try:
        for name in names:
            node_id = _resolve_taxon_node_id(resolved_dsn, name)
            if node_id is None:
                taxa.append(
                    {
                        "scientific_name": name,
                        "status": "not_found",
                        "nodes": [],
                        "edges": [],
                        "domain_coverage": {},
                    }
                )
                continue
            focal = repo.get_node(node_id)
            if focal is None:
                taxa.append(
                    {
                        "scientific_name": name,
                        "status": "not_found",
                        "nodes": [],
                        "edges": [],
                        "domain_coverage": {},
                    }
                )
                continue
            result = traverse(repo, focal, depth=depth, limit=limit, offset=0)
            taxa.append(
                {
                    "scientific_name": name,
                    "status": "found",
                    "focal_node": result.get("focal_node"),
                    "nodes": list(result.get("nodes") or []),
                    "edges": list(result.get("edges") or []),
                    "node_types": list(result.get("node_types") or []),
                    "edge_types": list(result.get("edge_types") or []),
                    "domain_coverage": dict(result.get("domain_coverage") or {}),
                    "data_gaps": list(result.get("data_gaps") or []),
                    "pagination": dict(result.get("pagination") or {}),
                }
            )
    except psycopg.Error as exc:
        return {
            "status": "unavailable",
            "reason": f"GRAPH_READ_FAILED:{exc.__class__.__name__}",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "requested_taxa": list(names),
            "taxa": [],
        }

    found = sum(item.get("status") == "found" for item in taxa)
    return {
        "status": "available",
        "read_only": True,
        "knowledge_graph_mutation": False,
        "resolution_policy": "explicit_binomial_exact_display_label_only",
        "requested_taxa": list(names),
        "found_taxa": found,
        "taxa": taxa,
    }
