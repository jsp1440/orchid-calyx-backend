"""Graph Intelligence Engine — first analytical increment (GRAPH-001A).

Per `Orchid-Continuum-Brain` `14_ENGINEERING/GRAPH-001A-implementation-directive.md`
("implement the smallest safe analytical pathway where architecture
permits: bounded graph snapshot; connected components; degree or weighted
degree; shortest path; reproducibility metadata; explicit truncation and
limitation warnings") and `01_GOVERNANCE/KO-0002-calyx-graph-intelligence-mandate.md`
("Every analysis preserves provenance, algorithm, version, parameters,
scope, software version, time, warnings, and limitations").

Deliberately the smallest safe increment, not the full blueprint:

- No new persistence. `bounded_snapshot` is a thin wrapper over the
  already-existing `traversal.traverse()`, which already reads from
  `GraphRepository` (`InMemoryGraphRepository` or `PostgresGraphRepository`)
  with an existing bound/truncation/pagination contract. Nothing here adds
  a table, a migration, or a write path.
- No new API surface. Nothing in `app/` imports this module yet; it is not
  reachable from any HTTP route. Per KO-0002's completion standard, "no
  placeholder endpoint may claim an unavailable capability is operational"
  - the simplest way to satisfy that for a first increment is to expose no
    endpoint at all until a real consumer (Mission Control or a future
    build) is ready to present these results honestly.
- Every result explicitly separates "computed within this bounded scope"
  from "true of the whole graph." Absence within a bounded snapshot is
  never reported as absence in the underlying data - this mirrors the same
  discipline `traversal.py` already applies to its own domain-gap reporting.

Subsequent GRAPH-001B..G increments (persisted analysis runs, an API
surface, Mission Control's Pipelines/GIE view, and connecting the
Vision/Literature/Evidence pipelines this module doesn't yet touch) are
listed, not built, in the Brain roadmap record accompanying this change.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from .models import Node
from .repository import GraphRepository
from .traversal import DEFAULT_LIMIT, traverse

ANALYTICS_ENGINE_VERSION = "GRAPH-001A.1"


def _reproducibility_metadata(
    *,
    algorithm: str,
    parameters: dict[str, Any],
    scope: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    """Every analytics function attaches one of these. Preserves algorithm
    identity, version, parameters, scope, computed_at, and explicit
    warnings/limitations - the exact fields KO-0002 requires, and the same
    shape every future GRAPH-001B+ increment should keep attaching."""
    return {
        "algorithm": algorithm,
        "engine_version": ANALYTICS_ENGINE_VERSION,
        "parameters": parameters,
        "scope": scope,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "warnings": list(warnings),
        "limitations": [
            (
                "Computed only over the bounded snapshot in scope, not the "
                "full graph - a node or edge absent from this result may "
                "simply be outside the bounded scope, not absent from the "
                "underlying data."
            ),
            (
                "Confidence-weighted results use each edge's stored "
                "confidence_score as a weight; an edge with no recorded "
                "confidence_score is treated as weight 1.0, not as a claim "
                "that its evidence is strong."
            ),
        ],
    }


def bounded_snapshot(
    repo: GraphRepository,
    focal: Node,
    *,
    depth: int = 1,
    limit: int = DEFAULT_LIMIT,
    node_types: Iterable[str] | None = None,
    edge_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """A reproducible, explicitly-bounded neighborhood around `focal`.

    Reuses `traversal.traverse()` for the actual bounded fetch (depth/limit
    clamping, truncation detection, domain-gap reporting all already exist
    there) and adds the reproducibility envelope every analytics result in
    this module carries. The focal node itself is included in
    `snapshot["nodes"]` (traverse() otherwise excludes it, since it is the
    query input rather than a traversal result) so downstream analytics
    functions never have to special-case it - an edge from the focal node
    is never silently dropped for referencing a node "outside" the node
    list.
    """
    result = traverse(
        repo, focal, depth=depth, node_types=node_types, edge_types=edge_types, limit=limit
    )
    result["nodes"] = [focal.to_dict()] + result["nodes"]

    warnings: list[str] = []
    if result["pagination"]["truncated"]:
        warnings.append(
            "Result truncated at the requested limit; not every edge "
            "within the requested scope was included."
        )

    result["reproducibility"] = _reproducibility_metadata(
        algorithm="bounded_snapshot",
        parameters={
            "depth": result["graph"]["depth"],
            "limit": result["pagination"]["limit"],
            "node_types": result["filters"]["node_types"],
            "edge_types": result["filters"]["edge_types"],
        },
        scope={
            "focal_node_id": focal.kg_node_id,
            "focal_canonical_key": focal.canonical_key,
        },
        warnings=warnings,
    )
    return result


def _snapshot_node_ids(snapshot: dict[str, Any]) -> set[int]:
    return {n["id"] for n in snapshot["nodes"]}


def connected_components(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Groups the snapshot's nodes into connected components.

    Edges are treated as undirected for component membership - whether two
    nodes are in the same component is a connectivity question, not a
    direction question. An edge referencing a node outside the snapshot
    (possible if truncation occurred) is skipped rather than treated as
    connecting to a phantom node - flagged in the result's warnings, not
    silently dropped.
    """
    node_ids = _snapshot_node_ids(snapshot)
    parent: dict[int, int] = {node_id: node_id for node_id in node_ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    skipped_edges = 0
    for edge in snapshot["edges"]:
        if edge["from"] in node_ids and edge["to"] in node_ids:
            union(edge["from"], edge["to"])
        else:
            skipped_edges += 1

    components: dict[int, list[int]] = {}
    for node_id in node_ids:
        components.setdefault(find(node_id), []).append(node_id)
    component_list = sorted(
        (sorted(members) for members in components.values()),
        key=lambda members: (-len(members), members[0] if members else 0),
    )

    warnings: list[str] = []
    if skipped_edges:
        warnings.append(
            f"{skipped_edges} edge(s) referenced a node outside the "
            "snapshot's node set (likely truncation) and were excluded "
            "from component membership."
        )

    return {
        "component_count": len(component_list),
        "largest_component_size": len(component_list[0]) if component_list else 0,
        "components": component_list,
        "reproducibility": _reproducibility_metadata(
            algorithm="connected_components",
            parameters={"directed": False},
            scope=dict(snapshot["reproducibility"]["scope"]),
            warnings=warnings,
        ),
    }


def degree(snapshot: dict[str, Any], *, weighted: bool = False) -> dict[str, Any]:
    """Per-node in/out/total degree within the snapshot.

    `weighted=True` sums each incident edge's `confidence_score` (default
    1.0 when absent - see the shared limitations note) instead of counting
    edges; the unweighted count is always included alongside so a caller
    never has to guess which one it received.
    """
    node_ids = _snapshot_node_ids(snapshot)
    in_count: dict[int, int] = {node_id: 0 for node_id in node_ids}
    out_count: dict[int, int] = {node_id: 0 for node_id in node_ids}
    in_weight: dict[int, float] = {node_id: 0.0 for node_id in node_ids}
    out_weight: dict[int, float] = {node_id: 0.0 for node_id in node_ids}

    skipped_edges = 0
    for edge in snapshot["edges"]:
        source, target = edge["from"], edge["to"]
        if source not in node_ids or target not in node_ids:
            skipped_edges += 1
            continue
        confidence = edge.get("confidence", {}) or {}
        weight = confidence.get("score")
        weight = 1.0 if weight is None else float(weight)
        out_count[source] += 1
        in_count[target] += 1
        out_weight[source] += weight
        in_weight[target] += weight

    by_node = {
        node_id: {
            "in_degree": in_count[node_id],
            "out_degree": out_count[node_id],
            "total_degree": in_count[node_id] + out_count[node_id],
            **(
                {
                    "in_weighted_degree": round(in_weight[node_id], 6),
                    "out_weighted_degree": round(out_weight[node_id], 6),
                    "total_weighted_degree": round(
                        in_weight[node_id] + out_weight[node_id], 6
                    ),
                }
                if weighted
                else {}
            ),
        }
        for node_id in node_ids
    }

    warnings: list[str] = []
    if skipped_edges:
        warnings.append(
            f"{skipped_edges} edge(s) referenced a node outside the "
            "snapshot's node set (likely truncation) and were excluded "
            "from degree counts."
        )

    return {
        "weighted": weighted,
        "by_node": by_node,
        "reproducibility": _reproducibility_metadata(
            algorithm="weighted_degree" if weighted else "degree",
            parameters={"weighted": weighted},
            scope=dict(snapshot["reproducibility"]["scope"]),
            warnings=warnings,
        ),
    }


def shortest_path(
    snapshot: dict[str, Any], source_id: int, target_id: int
) -> dict[str, Any]:
    """Fewest-hops directed path from `source_id` to `target_id` within the
    snapshot, via breadth-first search.

    Hop count, not evidence-weighted distance: edge `confidence_score`
    values are strength-of-evidence, not a notion of physical or semantic
    distance, so summing or minimizing them would manufacture a metric the
    data was never collected to support. A future increment building a
    genuinely weighted shortest-path notion should introduce it as an
    explicitly-named, explicitly-defined new algorithm rather than
    overloading this one.
    """
    node_ids = _snapshot_node_ids(snapshot)
    adjacency: dict[int, list[int]] = {node_id: [] for node_id in node_ids}
    skipped_edges = 0
    for edge in snapshot["edges"]:
        source, target = edge["from"], edge["to"]
        if source in node_ids and target in node_ids:
            adjacency[source].append(target)
        else:
            skipped_edges += 1

    warnings: list[str] = []
    if skipped_edges:
        warnings.append(
            f"{skipped_edges} edge(s) referenced a node outside the "
            "snapshot's node set (likely truncation) and were excluded "
            "from the search."
        )

    found = False
    path: list[int] = []
    if source_id not in node_ids or target_id not in node_ids:
        warnings.append(
            "Source and/or target node is not present in this bounded "
            "snapshot - a path may exist in the full graph even though "
            "none can be reported here."
        )
    else:
        predecessor: dict[int, int] = {}
        visited = {source_id}
        queue: deque[int] = deque([source_id])
        while queue:
            current = queue.popleft()
            if current == target_id:
                found = True
                break
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    predecessor[neighbor] = current
                    queue.append(neighbor)
        if found:
            node = target_id
            path = [node]
            while node != source_id:
                node = predecessor[node]
                path.append(node)
            path.reverse()

    return {
        "found": found,
        "path": path,
        "hop_count": (len(path) - 1) if found else None,
        "reproducibility": _reproducibility_metadata(
            algorithm="shortest_path_bfs_directed",
            parameters={"source_id": source_id, "target_id": target_id},
            scope=dict(snapshot["reproducibility"]["scope"]),
            warnings=warnings,
        ),
    }
