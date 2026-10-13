"""Deterministic workflow planning over compatible functional edges.

Planning is a breadth-first search from a source artifact type to a goal type.
Candidates are expanded in capability-id order, so the same registry and the
same request always yield the same plan. A function is used at most once per
path, and only each descriptor's first input and first output port take part
in FIL-001 planning (multi-port joins are future work).

The planner proposes; it does not execute, schedule, lease or authorize. A plan
is data handed to governance and, under FIL-001, to the dry-run executor only.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from app.calyx_orchestrator.executor import canonical_checksum

from .compatibility import FunctionalEdge, assess_input, check_edge
from .contracts import PLAN_SCHEMA, CapabilityDescriptor, ContractError, PortSpec
from .ontology import is_subtype, require_type
from .registry import FunctionalRegistry

MAX_PLAN_DEPTH = 8


@dataclass(frozen=True)
class SourceArtifact:
    """What a workflow starts from: a typed artifact and what is already true of it."""

    semantic_type: str
    evidence_states: tuple[str, ...]
    conditions: tuple[str, ...] = ()

    def port(self) -> PortSpec:
        return PortSpec(
            name="source",
            semantic_type=self.semantic_type,
            evidence_states=self.evidence_states,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_type": self.semantic_type,
            "evidence_states": sorted(set(self.evidence_states)),
            "conditions": sorted(set(self.conditions)),
        }


@dataclass(frozen=True)
class SourceEdge:
    """The edge from the workflow's source artifact into its first function."""

    consumer: CapabilityDescriptor
    input_port: str
    compatible: bool
    blocking_reasons: tuple[str, ...]
    advisories: tuple[str, ...]
    admitted_evidence_states: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": f"source->{self.consumer.capability_id}@{self.consumer.version}#{self.input_port}",
            "compatible": self.compatible,
            "blocking_reasons": list(self.blocking_reasons),
            "advisories": list(self.advisories),
            "admitted_evidence_states": list(self.admitted_evidence_states),
        }


@dataclass(frozen=True)
class WorkflowPlan:
    source: SourceArtifact
    goal_type: str
    no_api_mode: bool
    steps: tuple[CapabilityDescriptor, ...]
    source_edge: SourceEdge | None
    edges: tuple[FunctionalEdge, ...]
    rejected_edges: tuple[dict[str, Any], ...]

    @property
    def found(self) -> bool:
        return bool(self.steps)

    @property
    def plan_id(self) -> str:
        material = {
            "source": self.source.to_dict(),
            "goal_type": self.goal_type,
            "no_api_mode": self.no_api_mode,
            # The full descriptor, not just id@version: any material change to a
            # step (permissions, autonomy class, health, budget) changes the id.
            "steps": [step.to_dict() for step in self.steps],
        }
        return "fil-plan-" + canonical_checksum(material)[:16]

    @property
    def requires_human_gate(self) -> bool:
        return any(edge.requires_human_gate for edge in self.edges) or bool(
            self.source_edge and "HUMAN_GATE_REQUIRED" in self.source_edge.advisories
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "plan_id": self.plan_id,
            "found": self.found,
            "source": self.source.to_dict(),
            "goal_type": self.goal_type,
            "no_api_mode": self.no_api_mode,
            "steps": [
                {
                    "index": index,
                    "capability_id": step.capability_id,
                    "version": step.version,
                    "operator_class": step.operator_class.value,
                    "registry_capability": step.registry_capability,
                    "autonomy_class": step.autonomy_class.value,
                }
                for index, step in enumerate(self.steps)
            ],
            "source_edge": self.source_edge.to_dict() if self.source_edge else None,
            "edges": [edge.to_dict() for edge in self.edges],
            "rejected_edges": list(self.rejected_edges),
            "requires_human_gate": self.requires_human_gate,
            "execution_authority": False,
        }


def source_edge(
    source: SourceArtifact, consumer: CapabilityDescriptor, *, no_api_mode: bool
) -> SourceEdge:
    port = consumer.inputs[0].name
    blocking, advisories, admitted = assess_input(
        source.port(),
        tuple(sorted(set(source.conditions))),
        True,
        consumer,
        port,
        no_api_mode=no_api_mode,
    )
    return SourceEdge(consumer, port, not blocking, blocking, advisories, admitted)


def plan_workflow(
    registry: FunctionalRegistry,
    *,
    source: SourceArtifact,
    goal_type: str,
    no_api_mode: bool = True,
    max_depth: int = MAX_PLAN_DEPTH,
) -> WorkflowPlan:
    """Shortest compatible chain from ``source`` to a producer of ``goal_type``.

    When no chain exists the plan is returned empty with every rejected edge and
    its reason codes, so the refusal explains itself.
    """

    require_type(source.semantic_type)
    require_type(goal_type)
    if max_depth < 1:
        raise ContractError("NON_POSITIVE_PLAN_DEPTH")

    rejected: dict[str, tuple[str, ...]] = {}
    initial = tuple(sorted(set(source.conditions)))
    # Each entry: (path, source edge, edges, conditions true BEFORE the last step ran).
    queue: deque[
        tuple[
            tuple[CapabilityDescriptor, ...],
            SourceEdge,
            tuple[FunctionalEdge, ...],
            tuple[str, ...],
        ]
    ] = deque()

    for consumer in registry.descriptors():
        entry = source_edge(source, consumer, no_api_mode=no_api_mode)
        if not entry.compatible:
            rejected[entry.to_dict()["edge_id"]] = entry.blocking_reasons
            continue
        queue.append(((consumer,), entry, (), initial))

    # Breadth-first and shortest-first. Each (capability, upstream conditions)
    # state is expanded once: a later path reaching the same state is no shorter
    # and has the same successors, so re-expanding it only multiplies work.
    expanded: set[tuple[str, tuple[str, ...]]] = set()
    while queue:
        path, entry, edges, before_last = queue.popleft()
        last = path[-1]
        state = (last.capability_id, before_last)
        if is_subtype(last.outputs[0].semantic_type, goal_type):
            return WorkflowPlan(
                source,
                goal_type,
                no_api_mode,
                path,
                entry,
                edges,
                _rejections(rejected),
            )
        if len(path) >= max_depth or state in expanded:
            continue
        expanded.add(state)
        # Successors depend only on (last step, conditions before it), so a
        # capability may recur when conditions require it; deduplicating that
        # state is then exact and planning stays complete and polynomial.
        for consumer in registry.descriptors():
            edge = check_edge(
                last,
                last.outputs[0].name,
                consumer,
                consumer.inputs[0].name,
                upstream_conditions=before_last,
                no_api_mode=no_api_mode,
            )
            if not edge.compatible:
                rejected[edge.edge_id] = edge.blocking_reasons
                continue
            queue.append(
                ((*path, consumer), entry, (*edges, edge), edge.carried_conditions)
            )

    return WorkflowPlan(
        source, goal_type, no_api_mode, (), None, (), _rejections(rejected)
    )


def _rejections(rejected: dict[str, tuple[str, ...]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"edge_id": edge_id, "blocking_reasons": list(reasons)}
        for edge_id, reasons in sorted(rejected.items())
    )
