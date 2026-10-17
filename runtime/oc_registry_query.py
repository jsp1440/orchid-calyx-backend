"""Read-only Brain-consumable query interface for the OC Capability Registry.

This is the integration surface described by the A3 assignment (Phase 7) and
the verification follow-up (Phase 3): Brain, Calyx tooling, and Mission
Control consume the registry through this module rather than parsing
``registry/capability_registry.json`` themselves.

Hard boundaries (non-negotiable, mirroring the existing
``calyx-brain-capability-registry-v1`` rules):

* Read-only. Every response carries ``read_only: True`` and the interface
  exposes no mutation methods. The deterministic importer stays on
  ``CapabilityRegistry`` and produces a *new* registry object; nothing here
  schedules, queues, leases, executes, or publishes.
* No authority. This interface never decides what Brain is permitted to do;
  it reports what the verified evidence says exists, in what state.
* Fail-closed. Unknown node ids, unknown statuses, and unverified claims
  return explicit ``found: False`` / ``unknown`` results — never guesses,
  never exceptions for ordinary lookups.

Every response is a plain JSON-serializable dict tagged with the registry
contract and this interface version so consumers can pin compatibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from runtime.oc_capability_registry import (
    COMPAT_CONTRACT,
    CONTRACT,
    CapabilityRegistry,
    Edge,
    Node,
)

INTERFACE = "oc-registry-query-v1"

DEFAULT_STORE = (
    Path(__file__).resolve().parent.parent / "registry" / "capability_registry.json"
)

_STATUS_AXES = ("implementation", "test", "merge", "deployment", "operational")


def _envelope(**payload) -> dict:
    return {
        "contract": CONTRACT,
        "interface": INTERFACE,
        "compatible_with": COMPAT_CONTRACT,
        "read_only": True,
        "execution_authority": False,
        "publication_authority": False,
        **payload,
    }


def _node_view(node: Node) -> dict:
    return {
        "node_id": node.node_id,
        "kind": node.kind,
        "title": node.title,
        "parent_id": node.parent_id,
        "status": {axis: node.status.get(axis, "unknown") for axis in _STATUS_AXES},
        "repositories": sorted(node.repositories),
        "pull_requests": sorted(node.pull_requests),
        "db_objects": sorted(node.db_objects),
        "resource_requirements": node.resource_requirements,
        "blockers": sorted(node.blockers),
        "next_actions": sorted(node.next_actions),
    }


def _evidence_view(node_or_edge) -> list[dict]:
    return [
        {
            "source": e.source,
            "ref": e.ref,
            "observed_at": e.observed_at,
            **({"note": e.note} if e.note else {}),
        }
        for e in sorted(node_or_edge.evidence, key=lambda ev: ev.key())
    ]


def _unknown_lookup(node_id: str) -> dict:
    """Fail-closed status lookup for a node absent from the registry."""
    return _envelope(
        query="status-lookup",
        node_id=node_id,
        found=False,
        status={axis: "unknown" for axis in _STATUS_AXES},
        note="node is absent from the verified registry; all statuses unknown",
    )


class RegistryQuery:
    """Read-only query facade over an immutable CapabilityRegistry snapshot."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    @classmethod
    def from_default_store(cls, path: str | Path | None = None) -> "RegistryQuery":
        """Load the version-controlled store shipped in this repository."""
        return cls(CapabilityRegistry.from_json(path or DEFAULT_STORE))

    # ---------------------------------------------------------- discovery

    def discover_capabilities(
        self,
        query: str | None = None,
        *,
        module_id: str | None = None,
        statuses: dict[str, str] | None = None,
    ) -> dict:
        """Capability discovery: find capabilities/subcapabilities by title
        substring (case-insensitive), parent module, and/or exact status
        axis values. Empty filters list every capability."""
        results: list[dict] = []
        for node in sorted(
            self._registry._nodes.values(), key=lambda n: n.node_id  # noqa: SLF001
        ):
            if node.kind not in ("capability", "subcapability"):
                continue
            if module_id is not None and node.parent_id != module_id:
                continue
            if query and query.lower() not in (
                node.title.lower() + " " + node.node_id.lower()
            ):
                continue
            if statuses and any(
                node.status.get(axis, "unknown") != value
                for axis, value in statuses.items()
            ):
                continue
            results.append(_node_view(node))
        return _envelope(
            query="discover-capabilities",
            filters={
                "text": query,
                "module_id": module_id,
                "statuses": statuses or {},
            },
            count=len(results),
            capabilities=results,
        )

    # ------------------------------------------------------ status lookup

    def status_lookup(self, node_id: str) -> dict:
        """Full status + provenance for one node. Fail-closed on unknown id."""
        node = self._registry.get_node(node_id)
        if node is None:
            return _unknown_lookup(node_id)
        return _envelope(
            query="status-lookup",
            found=True,
            **_node_view(node),
            evidence=_evidence_view(node),
            eligibility=self._registry.eligibility(node_id),
        )

    # ----------------------------------------------------- relationships

    def module_relationships(self, node_id: str) -> dict:
        """Hierarchy and typed-graph relationships for one node: children,
        outgoing and incoming typed edges. Fail-closed on unknown id."""
        if self._registry.get_node(node_id) is None:
            return _unknown_lookup(node_id)
        children = [
            _node_view(child) for child in self._registry.children_of(node_id)
        ]
        outgoing: list[dict] = []
        incoming: list[dict] = []
        for edge in sorted(
            self._registry._edges.values(), key=Edge.key  # noqa: SLF001
        ):
            view = {
                "from_id": edge.from_id,
                "to_id": edge.to_id,
                "edge_type": edge.edge_type,
                "evidence": _evidence_view(edge),
            }
            if edge.from_id == node_id:
                outgoing.append(view)
            if edge.to_id == node_id:
                incoming.append(view)
        return _envelope(
            query="module-relationships",
            node_id=node_id,
            found=True,
            children=children,
            outgoing_edges=outgoing,
            incoming_edges=incoming,
        )

    # ------------------------------------------- missing / blocked surfacing

    def missing_and_blocked(self) -> dict:
        """Identify absent, blocked, and unmerged-but-implemented work.

        'missing' = capability whose implementation is recorded absent or
        unknown. 'blocked' = capability carrying blockers. 'unmerged' =
        implemented work sitting in open PRs. All fail-closed facts, no
        inference."""
        missing, blocked, unmerged = [], [], []
        for node in sorted(
            self._registry._nodes.values(), key=lambda n: n.node_id  # noqa: SLF001
        ):
            if node.kind not in ("capability", "subcapability"):
                continue
            if node.status.get("implementation") in ("absent", "unknown"):
                missing.append(_node_view(node))
            if node.blockers:
                blocked.append(_node_view(node))
            if node.status.get("merge") in ("open_pr", "open_draft_pr"):
                unmerged.append(_node_view(node))
        return _envelope(
            query="missing-and-blocked",
            counts={
                "missing": len(missing),
                "blocked": len(blocked),
                "unmerged": len(unmerged),
            },
            missing=missing,
            blocked=blocked,
            unmerged=unmerged,
        )

    # ------------------------------------------------------------ provenance

    def provenance(self, node_id: str) -> dict:
        """Evidence trail for one node plus the edges that touch it."""
        node = self._registry.get_node(node_id)
        if node is None:
            return _unknown_lookup(node_id)
        edge_evidence = [
            {
                "from_id": e.from_id,
                "to_id": e.to_id,
                "edge_type": e.edge_type,
                "evidence": _evidence_view(e),
            }
            for e in sorted(self._registry._edges.values(), key=Edge.key)  # noqa: SLF001
            if node_id in (e.from_id, e.to_id) and e.evidence
        ]
        return _envelope(
            query="provenance",
            node_id=node_id,
            found=True,
            evidence=_evidence_view(node),
            edge_evidence=edge_evidence,
        )

    # ------------------------------------------------ next engineering tasks

    def next_engineering_tasks(self) -> dict:
        """Aggregated, deterministic list of recorded blockers and next
        actions across all nodes — the registry's view of remaining
        engineering work. Read-only: ordering work remains Brain/Calyx's
        scheduler's job."""
        tasks: list[dict] = []
        for node in sorted(
            self._registry._nodes.values(), key=lambda n: n.node_id  # noqa: SLF001
        ):
            for action in sorted(node.next_actions):
                tasks.append({
                    "node_id": node.node_id,
                    "kind": "next_action",
                    "detail": action,
                })
            for blocker in sorted(node.blockers):
                tasks.append({
                    "node_id": node.node_id,
                    "kind": "blocker",
                    "detail": blocker,
                })
        return _envelope(
            query="next-engineering-tasks",
            count=len(tasks),
            tasks=tasks,
        )

    # -------------------------------------------------- Mission Control views

    def mission_control_export(self) -> dict:
        """Machine-readable bundle for Mission Control: accordion hierarchy,
        typed relationship graph, and summary counts, all from the same
        snapshot so the UI is internally consistent."""
        return _envelope(
            query="mission-control-export",
            hierarchy=self._registry.hierarchy_tree()["tree"],
            relationship_graph=self._registry.relationship_graph(),
            summary=self._registry.summary(),
        )

    def autonomy_brief(self) -> dict:
        """Pass-through of the engine's read-only autonomy brief."""
        return self._registry.autonomy_brief()


__all__ = ["INTERFACE", "RegistryQuery", "DEFAULT_STORE"]
