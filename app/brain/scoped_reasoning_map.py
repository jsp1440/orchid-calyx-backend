from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.brain.causal_scope import CausalScope, normalize_causal_scope
from app.brain.reasoning_map import ReasoningDirection, ReasoningMapEngine, ReasoningProfile
from app.brain.reasoning_scope import evaluate_edge_scope, evaluate_path_scope
from runtime.knowledge_graph import GraphRepository


class ScopedReasoningMapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_node_id: int = Field(gt=0)
    applicability_scope: CausalScope
    direction: ReasoningDirection = ReasoningDirection.FORWARD
    profile: ReasoningProfile = ReasoningProfile.ALL_RELATIONSHIPS
    max_depth: int = Field(default=4, ge=1, le=8)
    limit: int = Field(default=200, ge=1, le=1000)
    edge_types: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    causal_only: bool = True


def build_scoped_reasoning_map(
    repository: GraphRepository,
    request: ScopedReasoningMapRequest,
) -> dict[str, Any]:
    query_scope = normalize_causal_scope(request.applicability_scope)
    base = ReasoningMapEngine(repository).build(
        request.subject_node_id,
        direction=request.direction,
        profile=request.profile,
        max_depth=request.max_depth,
        limit=request.limit,
        edge_types=request.edge_types,
        causal_only=request.causal_only,
    )
    edges_by_id = {edge.kg_edge_id: edge for edge in repository.all_edges()}

    scoped_edges = []
    for serialized in base["edges"]:
        edge_id = int(serialized["id"])
        edge = edges_by_id.get(edge_id)
        evaluation = (
            evaluate_edge_scope(edge, query_scope)
            if edge is not None
            else {"status": "indeterminate", "applicable": None, "reason": "edge_not_found"}
        )
        scoped_edges.append({**serialized, "applicability": evaluation})

    scoped_paths = []
    for path in base["paths"]:
        path_edges = [
            edges_by_id[edge_id]
            for edge_id in path["edge_ids"]
            if edge_id in edges_by_id
        ]
        if len(path_edges) != len(path["edge_ids"]):
            applicability = {
                "status": "indeterminate",
                "applicable": None,
                "reason": "path_edge_not_found",
                "edge_evaluations": [],
                "out_of_scope_edge_ids": [],
                "indeterminate_edge_ids": list(path["edge_ids"]),
            }
        else:
            applicability = evaluate_path_scope(path_edges, query_scope)
        scoped_paths.append({**path, "applicability": applicability})

    status_counts = {"applicable": 0, "out_of_scope": 0, "indeterminate": 0}
    for path in scoped_paths:
        status = path["applicability"]["status"]
        if status in status_counts:
            status_counts[status] += 1

    base["configuration"]["applicability_scope"] = query_scope
    base["configuration"]["scope_evaluation"] = True
    base["edges"] = scoped_edges
    base["paths"] = scoped_paths
    base["scope_summary"] = {
        "query_scope": query_scope,
        "path_status_counts": status_counts,
        "fully_applicable_path_count": status_counts["applicable"],
        "out_of_scope_path_count": status_counts["out_of_scope"],
        "indeterminate_path_count": status_counts["indeterminate"],
        "safe_to_generalize": status_counts["out_of_scope"] == 0
        and status_counts["indeterminate"] == 0,
    }
    base["governance"].update(
        {
            "scope_aware": True,
            "unknown_scope_is_not_assumed_applicable": True,
            "out_of_scope_paths_are_retained_for_transparency": True,
            "scope_evaluation_does_not_prove_causality": True,
        }
    )
    return base
