"""Adapt measured Knowledge Graph readiness into Mission Control audit fields.

The legacy owner audit used a hard-coded list of relationship names whenever any
subsystem was incomplete. This module is deliberately pure: callers pass the
current live graph audit and receive relationship-specific fields derived only
from measured persisted graph state.
"""

from __future__ import annotations

from typing import Any

ALL_RELATIONSHIPS = (
    "taxonomy_to_images",
    "taxonomy_to_occurrences",
    "taxonomy_to_elevation",
    "taxonomy_to_climate",
    "taxonomy_to_literature",
    "taxonomy_to_pollinators",
    "taxonomy_to_mycorrhiza",
    "taxonomy_to_habitat",
    "taxonomy_to_conservation",
)


def relationship_audit_fields(graph_audit: dict[str, Any] | None) -> dict[str, Any]:
    """Return Mission Control relationship fields from a live persisted audit.

    No relationship is inferred from unrelated subsystem health. Missing means a
    persisted relationship was measured as absent or could not be measured.
    """
    if not graph_audit:
        return {
            "relationship_measurement_state": "unavailable",
            "missing_relationships": list(ALL_RELATIONSHIPS),
            "relationship_blockers": ["graph_relationship_audit_unavailable"],
            "knowledge_graph_node_edge_integrity": {
                "state": "unavailable",
                "passed": False,
            },
        }

    missing = [
        name
        for name in graph_audit.get("missing_relationships", [])
        if name in ALL_RELATIONSHIPS
    ]
    integrity = dict(
        graph_audit.get("knowledge_graph_node_edge_integrity")
        or (graph_audit.get("graph") or {}).get("integrity")
        or {"state": "unavailable", "passed": False}
    )
    blockers = list(graph_audit.get("blockers") or [])

    graph_state = (graph_audit.get("graph") or {}).get("state")
    if graph_state != "available":
        state = "unavailable"
    elif missing or integrity.get("state") != "available" or not integrity.get("passed"):
        state = "incomplete"
    else:
        state = "complete"

    return {
        "relationship_measurement_state": state,
        "missing_relationships": missing,
        "relationship_blockers": blockers,
        "knowledge_graph_node_edge_integrity": integrity,
    }


def merge_relationship_audit(
    payload: dict[str, Any],
    graph_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    """Replace legacy relationship placeholders with measured graph evidence."""
    result = dict(payload)
    measured = relationship_audit_fields(graph_audit)
    result.update(measured)
    sources = list(result.get("source_systems") or [])
    if "persisted_knowledge_graph_audit" not in sources:
        sources.append("persisted_knowledge_graph_audit")
    result["source_systems"] = sources

    unresolved = list(result.get("unresolved_failures") or [])
    for blocker in measured["relationship_blockers"]:
        if blocker not in unresolved:
            unresolved.append(blocker)
    result["unresolved_failures"] = unresolved
    return result
