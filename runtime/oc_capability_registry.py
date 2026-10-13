"""Orchid Continuum Capability Registry engine (oc-capability-registry-v1).

Extends the existing read-only capability-memory mechanism established by
``runtime/brain_capability_registry.py`` (contract
``calyx-brain-capability-registry-v1``) with:

* a version-controlled JSON backing store (``registry/capability_registry.json``),
* a hierarchical organization (Platform -> Division -> Module -> Capability ->
  Subcapability -> Implementation) with arbitrary nesting,
* a typed relationship graph between nodes,
* a deterministic, idempotent evidence importer, and
* read-only views for Mission Control and for the Brain/Calyx autonomy engine.

This module is read-only. It grants no execution, publication, or mutation
authority, mirroring the non-negotiable rule of the existing registries:
this registry can help decide *which* capability to use; it never decides
*what* anything is permitted to do.

Status discipline: unknown or unverified states are first-class and fail
closed. Deployment and operational status are never inferred from the mere
existence of code, tables, or workflows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

CONTRACT = "oc-capability-registry-v1"
COMPAT_CONTRACT = "calyx-brain-capability-registry-v1"

NodeKind = Literal[
    "platform", "division", "module", "capability", "subcapability", "implementation"
]
NODE_KINDS: tuple[str, ...] = (
    "platform", "division", "module", "capability", "subcapability", "implementation",
)
# A parent may only be of an earlier (broader) kind than its child.
_PARENT_KIND_RANK = {kind: rank for rank, kind in enumerate(NODE_KINDS)}

EdgeType = Literal[
    "depends_on",
    "implements",
    "verified_by",
    "consumes_data_from",
    "produces_data_for",
    "integrated_with",
    "blocked_by",
    "duplicates",
]
EDGE_TYPES: tuple[str, ...] = (
    "depends_on", "implements", "verified_by", "consumes_data_from",
    "produces_data_for", "integrated_with", "blocked_by", "duplicates",
)

# Independent status axes. Every axis is tracked separately; none is inferred
# from another. "unknown" = not inspected. "unverified" = inspected, but the
# available evidence cannot confirm the state.
IMPLEMENTATION_STATUS = ("implemented", "partial", "documented_only", "absent", "unknown")
TEST_STATUS = ("passing", "failing", "tests_present_unverified", "untested", "unknown")
MERGE_STATUS = ("merged", "open_pr", "open_draft_pr", "not_started", "unknown")
DEPLOYMENT_STATUS = ("deployed", "not_deployed", "owner_gated", "unverified", "unknown")
OPERATIONAL_STATUS = ("operational", "degraded", "down", "unverified", "unknown")

_STATUS_AXES: dict[str, tuple[str, ...]] = {
    "implementation": IMPLEMENTATION_STATUS,
    "test": TEST_STATUS,
    "merge": MERGE_STATUS,
    "deployment": DEPLOYMENT_STATUS,
    "operational": OPERATIONAL_STATUS,
}

# Informational rank used by the importer so that re-imports and overlapping
# evidence never downgrade a more-informed state to a less-informed one.
_UNINFORMED = {"unknown", "unverified"}

_NODE_ID_RE = re.compile(r"^oc\.(platform|division|module|capability|sub|impl)\.[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*$")


class RegistryValidationError(ValueError):
    """Raised when registry data violates the oc-capability-registry-v1 contract."""


@dataclass(frozen=True)
class Evidence:
    """One source observation supporting a node or edge claim."""

    source: str            # e.g. "github", "neon", "local-test"
    ref: str               # e.g. "jsp1440/orchid-calyx-backend@<sha>", "path", "PR #1811"
    observed_at: str       # ISO date of the observation (evidence time, not import time)
    note: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.source, self.ref, self.observed_at)


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: NodeKind
    title: str
    parent_id: str | None = None
    status: dict[str, str] = field(default_factory=lambda: {
        "implementation": "unknown",
        "test": "unknown",
        "merge": "unknown",
        "deployment": "unknown",
        "operational": "unknown",
    })
    repositories: tuple[str, ...] = ()
    pull_requests: tuple[str, ...] = ()
    db_objects: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    resource_requirements: str = ""
    blockers: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edge:
    from_id: str
    to_id: str
    edge_type: EdgeType
    evidence: tuple[Evidence, ...] = ()

    def key(self) -> tuple[str, str, str]:
        return (self.from_id, self.to_id, self.edge_type)


def _validate_status(status: dict[str, str], node_id: str) -> None:
    for axis, allowed in _STATUS_AXES.items():
        value = status.get(axis, "unknown")
        if value not in allowed:
            raise RegistryValidationError(
                f"{node_id}: status.{axis}={value!r} not in {allowed}"
            )


def _sorted_unique(strings: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(strings)))


class CapabilityRegistry:
    """Hierarchical + graph registry with fail-closed, read-only views."""

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        self._nodes: dict[str, Node] = {}
        for node in nodes:
            if node.node_id in self._nodes:
                raise RegistryValidationError(f"duplicate node_id: {node.node_id}")
            if not _NODE_ID_RE.match(node.node_id):
                raise RegistryValidationError(f"invalid node_id: {node.node_id}")
            if node.kind not in NODE_KINDS:
                raise RegistryValidationError(f"{node.node_id}: bad kind {node.kind}")
            _validate_status(node.status, node.node_id)
            self._nodes[node.node_id] = node

        self._edges: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            if edge.key() in self._edges:
                raise RegistryValidationError(f"duplicate edge: {edge.key()}")
            if edge.edge_type not in EDGE_TYPES:
                raise RegistryValidationError(f"bad edge_type: {edge.edge_type}")
            for endpoint in (edge.from_id, edge.to_id):
                if endpoint not in self._nodes:
                    raise RegistryValidationError(
                        f"edge {edge.key()} references unknown node {endpoint}"
                    )
            self._edges[edge.key()] = edge

        self._validate_hierarchy()

    # ------------------------------------------------------------------ #
    # construction / validation
    # ------------------------------------------------------------------ #

    def _validate_hierarchy(self) -> None:
        roots = [n for n in self._nodes.values() if n.parent_id is None]
        if len(roots) != 1 or roots[0].kind != "platform":
            raise RegistryValidationError(
                "registry must have exactly one root node of kind 'platform'"
            )
        for node in self._nodes.values():
            if node.parent_id is None:
                continue
            parent = self._nodes.get(node.parent_id)
            if parent is None:
                raise RegistryValidationError(
                    f"{node.node_id}: unknown parent {node.parent_id}"
                )
            if _PARENT_KIND_RANK[parent.kind] >= _PARENT_KIND_RANK[node.kind]:
                raise RegistryValidationError(
                    f"{node.node_id}: kind {node.kind} cannot nest under {parent.kind}"
                )
        # cycle check on parent links
        for node in self._nodes.values():
            seen = {node.node_id}
            current = node.parent_id
            while current is not None:
                if current in seen:
                    raise RegistryValidationError(
                        f"parent cycle detected at {node.node_id}"
                    )
                seen.add(current)
                current = self._nodes[current].parent_id

    @classmethod
    def from_dict(cls, payload: dict) -> "CapabilityRegistry":
        if payload.get("contract") != CONTRACT:
            raise RegistryValidationError(
                f"contract must be {CONTRACT!r}, got {payload.get('contract')!r}"
            )
        nodes = []
        for raw in payload.get("nodes", []):
            evidence = tuple(Evidence(**e) for e in raw.get("evidence", []))
            nodes.append(
                Node(
                    node_id=raw["node_id"],
                    kind=raw["kind"],
                    title=raw["title"],
                    parent_id=raw.get("parent_id"),
                    status=dict(raw.get("status", {})) or Node(
                        raw["node_id"], raw["kind"], raw["title"]
                    ).status,
                    repositories=tuple(raw.get("repositories", [])),
                    pull_requests=tuple(raw.get("pull_requests", [])),
                    db_objects=tuple(raw.get("db_objects", [])),
                    evidence=evidence,
                    resource_requirements=raw.get("resource_requirements", ""),
                    blockers=tuple(raw.get("blockers", [])),
                    next_actions=tuple(raw.get("next_actions", [])),
                )
            )
        edges = [
            Edge(
                from_id=e["from_id"],
                to_id=e["to_id"],
                edge_type=e["edge_type"],
                evidence=tuple(Evidence(**x) for x in e.get("evidence", [])),
            )
            for e in payload.get("edges", [])
        ]
        return cls(nodes, edges)

    @classmethod
    def from_json(cls, path: str | Path) -> "CapabilityRegistry":
        with open(path, encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    # ------------------------------------------------------------------ #
    # serialization (deterministic: stable ordering, no wall-clock)
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        def ev_dict(e: Evidence) -> dict:
            out = {"source": e.source, "ref": e.ref, "observed_at": e.observed_at}
            if e.note:
                out["note"] = e.note
            return out

        nodes = []
        for node in sorted(self._nodes.values(), key=lambda n: n.node_id):
            nodes.append({
                "node_id": node.node_id,
                "kind": node.kind,
                "title": node.title,
                "parent_id": node.parent_id,
                "status": {axis: node.status.get(axis, "unknown") for axis in _STATUS_AXES},
                "repositories": sorted(node.repositories),
                "pull_requests": sorted(node.pull_requests),
                "db_objects": sorted(node.db_objects),
                "evidence": [ev_dict(e) for e in sorted(node.evidence, key=Evidence.key)],
                "resource_requirements": node.resource_requirements,
                "blockers": sorted(node.blockers),
                "next_actions": sorted(node.next_actions),
            })
        edges = [
            {
                "from_id": e.from_id,
                "to_id": e.to_id,
                "edge_type": e.edge_type,
                "evidence": [ev_dict(x) for x in sorted(e.evidence, key=Evidence.key)],
            }
            for e in sorted(self._edges.values(), key=Edge.key)
        ]
        return {"contract": CONTRACT, "nodes": nodes, "edges": edges}

    def to_json(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, sort_keys=False)
            handle.write("\n")

    # ------------------------------------------------------------------ #
    # deterministic, idempotent evidence import
    # ------------------------------------------------------------------ #

    def import_records(self, records: Iterable[dict]) -> "CapabilityRegistry":
        """Merge evidence records into a new registry.

        Deterministic: output depends only on input content, never on wall
        clock or record ordering. Idempotent: importing the same records twice
        yields byte-identical JSON. An informed status is never downgraded to
        ``unknown``/``unverified`` by later evidence.
        """
        nodes: dict[str, Node] = dict(self._nodes)
        edges: dict[tuple[str, str, str], Edge] = dict(self._edges)

        for record in sorted(records, key=lambda r: r.get("node_id", "")):
            node_id = record["node_id"]
            existing = nodes.get(node_id)
            if existing is None:
                existing = Node(
                    node_id=node_id,
                    kind=record.get("kind", "capability"),
                    title=record.get("title", node_id),
                    parent_id=record.get("parent_id"),
                )
            status = dict(existing.status)
            for axis, value in record.get("status", {}).items():
                if axis not in _STATUS_AXES:
                    raise RegistryValidationError(f"{node_id}: unknown axis {axis}")
                if value not in _STATUS_AXES[axis]:
                    raise RegistryValidationError(
                        f"{node_id}: bad value {value!r} for {axis}"
                    )
                current = status.get(axis, "unknown")
                if current in _UNINFORMED or value not in _UNINFORMED:
                    # later informed evidence wins; informed state is never
                    # downgraded to unknown/unverified
                    if not (current not in _UNINFORMED and value in _UNINFORMED):
                        status[axis] = value
            nodes[node_id] = Node(
                node_id=existing.node_id,
                kind=existing.kind,
                title=existing.title,
                parent_id=record.get("parent_id", existing.parent_id),
                status=status,
                repositories=_sorted_unique(
                    (*existing.repositories, *record.get("repositories", []))
                ),
                pull_requests=_sorted_unique(
                    (*existing.pull_requests, *record.get("pull_requests", []))
                ),
                db_objects=_sorted_unique(
                    (*existing.db_objects, *record.get("db_objects", []))
                ),
                evidence=tuple(sorted(
                    {e.key(): e for e in (
                        *existing.evidence,
                        *(Evidence(**x) for x in record.get("evidence", [])),
                    )}.values(), key=Evidence.key
                )),
                resource_requirements=(
                    record.get("resource_requirements") or existing.resource_requirements
                ),
                blockers=_sorted_unique(
                    (*existing.blockers, *record.get("blockers", []))
                ),
                next_actions=_sorted_unique(
                    (*existing.next_actions, *record.get("next_actions", []))
                ),
            )
            for raw_edge in record.get("edges", []):
                edge = Edge(
                    from_id=raw_edge["from_id"],
                    to_id=raw_edge["to_id"],
                    edge_type=raw_edge["edge_type"],
                )
                prior = edges.get(edge.key())
                merged_evidence = tuple(sorted(
                    {e.key(): e for e in (
                        *(prior.evidence if prior else ()),
                        *(Evidence(**x) for x in raw_edge.get("evidence", [])),
                    )}.values(), key=Evidence.key
                ))
                edges[edge.key()] = Edge(
                    edge.from_id, edge.to_id, edge.edge_type, merged_evidence
                )

        return CapabilityRegistry(nodes.values(), edges.values())

    # ------------------------------------------------------------------ #
    # read-only views
    # ------------------------------------------------------------------ #

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def children_of(self, node_id: str) -> tuple[Node, ...]:
        return tuple(sorted(
            (n for n in self._nodes.values() if n.parent_id == node_id),
            key=lambda n: n.node_id,
        ))

    def dependencies_of(self, node_id: str) -> tuple[Edge, ...]:
        return tuple(sorted(
            (e for e in self._edges.values()
             if e.from_id == node_id and e.edge_type == "depends_on"),
            key=Edge.key,
        ))

    def hierarchy_tree(self) -> dict:
        """Accordion-friendly nested tree for Mission Control."""

        def build(node: Node) -> dict:
            return {
                "node_id": node.node_id,
                "kind": node.kind,
                "title": node.title,
                "status": {axis: node.status.get(axis, "unknown") for axis in _STATUS_AXES},
                "blockers": sorted(node.blockers),
                "children": [build(child) for child in self.children_of(node.node_id)],
            }

        root = next(n for n in self._nodes.values() if n.parent_id is None)
        return {
            "contract": CONTRACT,
            "view": "mission-control-hierarchy",
            "read_only": True,
            "tree": build(root),
        }

    def relationship_graph(self) -> dict:
        """Typed relationship graph export (cross-module interactions)."""
        return {
            "contract": CONTRACT,
            "view": "relationship-graph",
            "read_only": True,
            "nodes": [
                {"node_id": n.node_id, "kind": n.kind, "title": n.title}
                for n in sorted(self._nodes.values(), key=lambda n: n.node_id)
            ],
            "edges": [
                {"from_id": e.from_id, "to_id": e.to_id, "edge_type": e.edge_type}
                for e in sorted(self._edges.values(), key=Edge.key)
            ],
        }

    def eligibility(self, node_id: str) -> dict:
        """Fail-closed eligibility, compatible in spirit with the existing
        calyx-brain-capability-registry-v1 mechanism: a capability is eligible
        only if it is implemented, merged, and tested, and every depends_on
        upstream is eligible. Unknown/unverified states fail closed.
        """
        return self._eligibility(node_id, path=())

    def _eligibility(self, node_id: str, *, path: tuple[str, ...]) -> dict:
        node = self._nodes.get(node_id)
        if node is None:
            return {
                "node_id": node_id,
                "eligible": False,
                "reasons": ["node is absent from the verified registry"],
            }
        if node_id in path:
            cycle = " -> ".join((*path, node_id))
            return {
                "node_id": node_id,
                "eligible": False,
                "reasons": [f"dependency cycle: {cycle}"],
            }
        reasons: list[str] = []
        status = node.status
        if status.get("implementation") != "implemented":
            reasons.append(f"implementation is {status.get('implementation')}, not implemented")
        if status.get("test") != "passing":
            reasons.append(f"test is {status.get('test')}, not passing")
        if status.get("merge") != "merged":
            reasons.append(f"merge is {status.get('merge')}, not merged")
        reasons.extend(f"blocker: {b}" for b in node.blockers)
        for edge in self.dependencies_of(node_id):
            upstream = self._eligibility(edge.to_id, path=(*path, node_id))
            if not upstream["eligible"]:
                detail = "; ".join(str(r) for r in upstream["reasons"])
                reasons.append(f"dependency ineligible: {edge.to_id} ({detail})")
        return {"node_id": node_id, "eligible": not reasons, "reasons": reasons}

    def autonomy_brief(self) -> dict:
        """Read-only export for the Brain/Calyx autonomy engine.

        Surfaces, without any scheduling or execution authority:
        unmet requirements, blocked dependencies, untested capabilities,
        unmerged implementation work, missing data sources, duplicated work,
        and integration-ready capabilities.
        """
        capabilities = [
            n for n in self._nodes.values()
            if n.kind in ("capability", "subcapability")
        ]
        untested, unmerged, blocked, missing_data, ready = [], [], [], [], []
        for node in sorted(capabilities, key=lambda n: n.node_id):
            if node.status.get("test") in ("untested", "tests_present_unverified"):
                untested.append(node.node_id)
            if node.status.get("merge") in ("open_pr", "open_draft_pr"):
                unmerged.append(node.node_id)
            if node.blockers or node.status.get("implementation") == "absent":
                blocked.append(node.node_id)
            if not node.db_objects and node.kind == "capability" and (
                node.status.get("deployment") in _UNINFORMED
            ):
                missing_data.append(node.node_id)
            result = self.eligibility(node.node_id)
            if result["eligible"]:
                ready.append(node.node_id)
        duplicated = sorted({
            e.from_id for e in self._edges.values() if e.edge_type == "duplicates"
        } | {
            e.to_id for e in self._edges.values() if e.edge_type == "duplicates"
        })
        return {
            "contract": CONTRACT,
            "compatible_with": COMPAT_CONTRACT,
            "read_only": True,
            "publication_authority": False,
            "execution_authority": False,
            "untested_capabilities": untested,
            "unmerged_work": unmerged,
            "blocked_or_absent": blocked,
            "missing_verified_data_support": missing_data,
            "duplicated_work": duplicated,
            "integration_ready": ready,
        }

    def summary(self) -> dict:
        counts = {kind: 0 for kind in NODE_KINDS}
        for node in self._nodes.values():
            counts[node.kind] += 1
        return {
            "contract": CONTRACT,
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "by_kind": counts,
        }
