from __future__ import annotations

from typing import Any, Iterable

from app.brain.causal_scope import CausalScope, normalize_causal_scope
from runtime.knowledge_graph import Edge


_LIST_DIMENSIONS = ("taxa", "organs", "tissues", "cell_types", "developmental_stages")
_MAP_DIMENSIONS = ("environments", "treatments", "cultivation_context", "population_context")


def _edge_scope(edge: Edge) -> dict[str, Any]:
    payload = edge.payload or {}
    return normalize_causal_scope(payload.get("causal_scope"))


def _mapping_compatible(claim: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, requested in query.items():
        if key in claim and claim[key] != requested:
            return False
    return True


def evaluate_scope(
    claim_scope: dict[str, Any] | CausalScope | None,
    query_scope: dict[str, Any] | CausalScope | None,
) -> dict[str, Any]:
    claim = normalize_causal_scope(claim_scope)
    if query_scope is None:
        return {
            "status": "not_evaluated",
            "applicable": None,
            "claim_scope": claim,
            "query_scope": None,
            "matched_dimensions": [],
            "mismatched_dimensions": [],
            "unresolved_dimensions": [],
        }

    query = normalize_causal_scope(query_scope)
    if claim["scope_class"] == "global":
        return {
            "status": "applicable",
            "applicable": True,
            "claim_scope": claim,
            "query_scope": query,
            "matched_dimensions": ["global"],
            "mismatched_dimensions": [],
            "unresolved_dimensions": [],
        }
    if claim["scope_class"] == "unknown":
        return {
            "status": "indeterminate",
            "applicable": None,
            "claim_scope": claim,
            "query_scope": query,
            "matched_dimensions": [],
            "mismatched_dimensions": [],
            "unresolved_dimensions": ["claim_scope_unknown"],
        }

    matched: list[str] = []
    mismatched: list[str] = []
    unresolved: list[str] = []
    for dimension in _LIST_DIMENSIONS:
        claim_values = set(claim[dimension])
        query_values = set(query[dimension])
        if not claim_values:
            continue
        if not query_values:
            unresolved.append(dimension)
        elif claim_values.intersection(query_values):
            matched.append(dimension)
        else:
            mismatched.append(dimension)

    for dimension in _MAP_DIMENSIONS:
        claim_values = claim[dimension]
        query_values = query[dimension]
        if not claim_values:
            continue
        if not query_values:
            unresolved.append(dimension)
        elif _mapping_compatible(claim_values, query_values):
            matched.append(dimension)
        else:
            mismatched.append(dimension)

    if mismatched:
        status, applicable = "out_of_scope", False
    elif unresolved:
        status, applicable = "indeterminate", None
    else:
        status, applicable = "applicable", True
    return {
        "status": status,
        "applicable": applicable,
        "claim_scope": claim,
        "query_scope": query,
        "matched_dimensions": sorted(matched),
        "mismatched_dimensions": sorted(mismatched),
        "unresolved_dimensions": sorted(unresolved),
    }


def evaluate_edge_scope(edge: Edge, query_scope: dict[str, Any] | CausalScope | None) -> dict[str, Any]:
    return evaluate_scope(_edge_scope(edge), query_scope)


def evaluate_path_scope(
    edges: Iterable[Edge],
    query_scope: dict[str, Any] | CausalScope | None,
) -> dict[str, Any]:
    evaluations = [evaluate_edge_scope(edge, query_scope) for edge in edges]
    statuses = [item["status"] for item in evaluations]
    if query_scope is None:
        status, applicable = "not_evaluated", None
    elif "out_of_scope" in statuses:
        status, applicable = "out_of_scope", False
    elif "indeterminate" in statuses:
        status, applicable = "indeterminate", None
    else:
        status, applicable = "applicable", True
    return {
        "status": status,
        "applicable": applicable,
        "edge_evaluations": evaluations,
        "out_of_scope_edge_ids": [
            edge.kg_edge_id
            for edge, evaluation in zip(edges, evaluations)
            if evaluation["status"] == "out_of_scope"
        ],
        "indeterminate_edge_ids": [
            edge.kg_edge_id
            for edge, evaluation in zip(edges, evaluations)
            if evaluation["status"] == "indeterminate"
        ],
    }
