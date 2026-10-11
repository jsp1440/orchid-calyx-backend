"""Deterministic functional-edge compatibility.

An edge connects one producer output port to one consumer input port. It is
compatible only when every check below passes; each failed check is reported
by a stable reason code so a refusal can be read, counted and repaired rather
than re-tried. Advisories never make an edge incompatible.

Blocking reason codes:

``SEMANTIC_TYPE_MISMATCH``
    The producer's type is not the consumer's type or a subtype of it.
``EVIDENCE_STATE_INADMISSIBLE``
    No evidence state the producer can emit is admitted by the consumer.
``PRECONDITION_UNSATISFIED:<condition>``
    A consumer precondition is neither an effect of the producer nor carried
    from further upstream.
``PROVENANCE_CHAIN_BROKEN``
    The consumer needs an upstream provenance chain the producer does not keep.
``AUTONOMY_PROHIBITED``
    The consumer is autonomy class D.
``PROVIDER_PARKED_NO_API``
    The consumer needs a paid provider and NO-API mode is active.
``CAPABILITY_NOT_EXECUTABLE:<status>``
    The consumer's declared status has no implementation to run.

Advisory codes: ``EVIDENCE_STATES_FILTERED:<states>`` (the consumer will hold
back items in those states), ``HUMAN_GATE_REQUIRED`` (consumer is class B),
``PROPOSAL_ONLY`` (consumer is class C).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import (
    DRY_RUN_EXECUTABLE_STATUSES,
    EDGE_SCHEMA,
    AutonomyClass,
    CapabilityDescriptor,
    PortSpec,
)
from .ontology import is_subtype, require_type


@dataclass(frozen=True)
class FunctionalEdge:
    producer: CapabilityDescriptor
    output_port: str
    consumer: CapabilityDescriptor
    input_port: str
    compatible: bool
    blocking_reasons: tuple[str, ...]
    advisories: tuple[str, ...]
    admitted_evidence_states: tuple[str, ...]
    carried_conditions: tuple[str, ...]

    @property
    def edge_id(self) -> str:
        return (
            f"{self.producer.capability_id}@{self.producer.version}#{self.output_port}"
            f"->{self.consumer.capability_id}@{self.consumer.version}#{self.input_port}"
        )

    @property
    def requires_human_gate(self) -> bool:
        return "HUMAN_GATE_REQUIRED" in self.advisories

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EDGE_SCHEMA,
            "edge_id": self.edge_id,
            "producer": {
                "capability_id": self.producer.capability_id,
                "version": self.producer.version,
                "port": self.output_port,
                "semantic_type": self.producer.output(self.output_port).semantic_type,
            },
            "consumer": {
                "capability_id": self.consumer.capability_id,
                "version": self.consumer.version,
                "port": self.input_port,
                "semantic_type": self.consumer.input(self.input_port).semantic_type,
            },
            "compatible": self.compatible,
            "blocking_reasons": list(self.blocking_reasons),
            "advisories": list(self.advisories),
            "admitted_evidence_states": list(self.admitted_evidence_states),
            "carried_conditions": list(self.carried_conditions),
            "requires_human_gate": self.requires_human_gate,
        }


def assess_input(
    produced: PortSpec,
    available_conditions: tuple[str, ...],
    chain_preserved: bool,
    consumer: CapabilityDescriptor,
    input_port: str,
    *,
    no_api_mode: bool = True,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The single compatibility rule: can ``consumer`` accept this artifact?

    Returns ``(blocking_reasons, advisories, admitted_evidence_states)``. Used
    for capability-to-capability edges and for a workflow's source artifact
    alike, so the two can never disagree.
    """

    required = consumer.input(input_port)
    require_type(produced.semantic_type)
    require_type(required.semantic_type)

    blocking: list[str] = []
    advisories: list[str] = []

    if not is_subtype(produced.semantic_type, required.semantic_type):
        blocking.append("SEMANTIC_TYPE_MISMATCH")

    admitted = tuple(
        sorted(set(produced.evidence_states) & set(required.evidence_states))
    )
    filtered = sorted(set(produced.evidence_states) - set(required.evidence_states))
    if not admitted:
        blocking.append("EVIDENCE_STATE_INADMISSIBLE")
    elif filtered:
        advisories.append(f"EVIDENCE_STATES_FILTERED:{','.join(filtered)}")

    for condition in consumer.preconditions:
        if condition not in available_conditions:
            blocking.append(f"PRECONDITION_UNSATISFIED:{condition}")

    if consumer.provenance.requires_upstream_chain and not chain_preserved:
        blocking.append("PROVENANCE_CHAIN_BROKEN")

    if consumer.autonomy_class is AutonomyClass.PROHIBITED:
        blocking.append("AUTONOMY_PROHIBITED")
    elif consumer.autonomy_class is AutonomyClass.HUMAN_APPROVAL:
        advisories.append("HUMAN_GATE_REQUIRED")
    elif consumer.autonomy_class is AutonomyClass.PROPOSAL_ONLY:
        advisories.append("PROPOSAL_ONLY")

    if consumer.provider_required and no_api_mode:
        blocking.append("PROVIDER_PARKED_NO_API")

    if consumer.health.status not in DRY_RUN_EXECUTABLE_STATUSES:
        blocking.append(f"CAPABILITY_NOT_EXECUTABLE:{consumer.health.status}")

    return tuple(blocking), tuple(advisories), admitted


def carried_conditions(
    producer: CapabilityDescriptor, upstream_conditions: tuple[str, ...]
) -> tuple[str, ...]:
    """Conditions true of a producer's output.

    A producer that does not preserve the provenance chain drops what was
    certified upstream; only its own effects survive it.
    """
    inherited = (
        set(upstream_conditions) if producer.provenance.preserves_chain else set()
    )
    return tuple(sorted(inherited | set(producer.effects)))


def check_edge(
    producer: CapabilityDescriptor,
    output_port: str,
    consumer: CapabilityDescriptor,
    input_port: str,
    *,
    upstream_conditions: tuple[str, ...] = (),
    no_api_mode: bool = True,
) -> FunctionalEdge:
    """Evaluate one producer -> consumer edge. Pure and deterministic.

    ``upstream_conditions`` are conditions established before the producer ran.
    """

    carried = carried_conditions(producer, upstream_conditions)
    blocking, advisories, admitted = assess_input(
        producer.output(output_port),
        carried,
        producer.provenance.preserves_chain,
        consumer,
        input_port,
        no_api_mode=no_api_mode,
    )
    return FunctionalEdge(
        producer=producer,
        output_port=output_port,
        consumer=consumer,
        input_port=input_port,
        compatible=not blocking,
        blocking_reasons=blocking,
        advisories=advisories,
        admitted_evidence_states=admitted,
        carried_conditions=carried,
    )
