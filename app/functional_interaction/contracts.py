"""FIL-001 versioned capability contracts.

A Functional Interaction Layer descriptor states, for one existing software
function, what it consumes, what it produces, what must be true before it runs,
what it makes true afterwards, and what authority it needs. It is a description
layered over the registries that already exist -- never a second registry of
what the Continuum can do:

* ``registry_capability`` must name a capability already classified in
  :mod:`app.provider_reservoir.capabilities`; an unclassified name raises
  :class:`~app.provider_reservoir.capabilities.CapabilityUnknown` exactly as
  provider routing does.
* ``health.status`` uses the status vocabulary of
  :mod:`runtime.brain_capability_registry`, and ``brain_capability_id`` links a
  descriptor to an evidence-pinned entry there when one exists.
* Prohibited permissions are :data:`app.calyx_orchestrator.executor.PROHIBITED_CAPABILITIES`.
* Event names are values of
  :class:`app.scientific_observability.models.ObservationEventType`.

Operator classes classify functions; they are not services, agents or queues.
Nothing in this module executes anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, get_args

from app.calyx_orchestrator.executor import PROHIBITED_CAPABILITIES
from app.provider_reservoir.capabilities import CAPABILITIES, is_provider_capability
from app.scientific_observability.models import ObservationEventType
from runtime.brain_capability_registry import CapabilityStatus

DESCRIPTOR_SCHEMA = "oc.fil.capability-descriptor.v1"
EDGE_SCHEMA = "oc.fil.functional-edge.v1"
RECEIPT_SCHEMA = "oc.fil.execution-receipt.v1"
PLAN_SCHEMA = "oc.fil.workflow-plan.v1"

CAPABILITY_STATUSES: tuple[str, ...] = get_args(CapabilityStatus)

#: Statuses whose implementation exists in this repository and may therefore be
#: exercised in a deterministic dry run. Production execution would require
#: ``OPERATIONAL`` and is not something FIL-001 can authorize at all.
DRY_RUN_EXECUTABLE_STATUSES = frozenset(
    {"OPERATIONAL", "IMPLEMENTED_NOT_INTEGRATED", "PARTIAL"}
)

#: The ten evidence states the Continuum keeps distinct (``AGENT-OPERATING-MEMORY``
#: and ``app/research_traits/service.py::SAFE_STATES``). Kept as a literal here so
#: this module stays importable without a database driver; a test asserts the
#: two agree.
EVIDENCE_STATES = frozenset(
    {
        "AVAILABLE",
        "PROVISIONAL",
        "VERIFIED",
        "CONTRADICTORY",
        "UNKNOWN",
        "UNAVAILABLE",
        "WITHHELD",
        "ABSENT",
        "REJECTED",
        "SUPERSEDED",
    }
)

#: Authority recorded on taxon links produced from FIL's *invented* fixture
#: backbones. They are built with the World Plants spine builder but are not a
#: World Plants release, so fixture output must never claim ``world_plants``.
FIXTURE_TAXON_AUTHORITY = "fil_fixture_backbone"

#: States no automated function may assign. VERIFIED requires human review.
HUMAN_ONLY_EVIDENCE_STATES = frozenset({"VERIFIED"})

#: Permissions a safe-autonomous (class A) function may hold. Identical to
#: ``app.calyx_orchestrator.service.EXECUTABLE_POLICY_CLASSES``; a test asserts it.
SAFE_AUTONOMOUS_PERMISSIONS = frozenset({"read_only_research", "candidate_generation"})

#: Conditions a function may never claim to establish. A descriptor that lists
#: one of these as an effect is describing publication or promotion, which no
#: FIL-described function performs.
FORBIDDEN_EFFECTS = frozenset(
    {
        "scientifically_published",
        "knowledge_promoted",
        "taxonomy_activated",
        "production_mutated",
        "evidence_verified",
    }
)

#: Statuses a taxon link may carry. ``synonym`` means the submitted name is a
#: synonym and the link points at the accepted taxon; ``ambiguous`` means more
#: than one taxon matched and nothing was chosen.
TAXON_LINK_STATUSES = ("accepted", "ambiguous", "synonym", "unresolved")

#: The canonical backbone (``runtime.knowledge_graph.canonical_taxonomy``).
#: Literal so this module stays importable without that package's driver.
CANONICAL_TAXON_AUTHORITY = "world_plants"

_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SEMANTIC_TYPE = re.compile(r"^oc:[A-Z][A-Za-z0-9]*$")
_REASON_CODE = re.compile(r"^[A-Z0-9_:]+$")
_CONDITION = re.compile(r"^[a-z][a-z0-9_]*$")


class OperatorClass(StrEnum):
    """The role a function plays in a functional interaction.

    Named after the biological analogy in the Brain's Autonomous Operations
    Playbook. A classification of software behaviour only.
    """

    #: Accepts an external signal or record into the system unchanged in meaning.
    RECEPTOR = "receptor"
    #: Surveys a population of records for a pattern without changing them.
    SCANNER = "scanner"
    #: Converts a signal from one representation into another (text -> claims).
    TRANSDUCER = "transducer"
    #: Transforms a substrate deterministically into a product (normalization).
    ENZYME = "enzyme"
    #: Moves a record across a boundary (repository, lane, store) unchanged.
    TRANSPORTER = "transporter"
    #: Maps identities between vocabularies or authorities (name -> taxon id).
    ADAPTOR = "adaptor"
    #: Combines several inputs into one assessed whole (reasoning, aggregation).
    INTEGRATOR = "integrator"
    #: Adjusts the rate or priority of other functions without doing their work.
    MODULATOR = "modulator"
    #: Routes flow between alternatives on a deterministic condition.
    SWITCH = "switch"
    #: Fires on a schedule. FIL describes existing schedules; it adds none.
    OSCILLATOR = "oscillator"
    #: Holds records pending a decision without promoting them (review queues).
    BUFFER = "buffer"
    #: Fans a signal out to more consumers or a larger audience.
    AMPLIFIER = "amplifier"
    #: Checks a record against a contract and assigns an explicit verdict.
    VALIDATOR = "validator"
    #: Stops a flow that would cross a boundary (gates, kill switches).
    INHIBITOR = "inhibitor"
    #: Restores a failed or drifted state to a known-good one.
    REPAIR_OPERATOR = "repair_operator"


class AutonomyClass(StrEnum):
    """The Brain playbook's A/B/C/D autonomy classes, unchanged.

    FIL does not define autonomy; it records which existing class a function is in.
    """

    SAFE_AUTONOMOUS = "A"
    HUMAN_APPROVAL = "B"
    PROPOSAL_ONLY = "C"
    PROHIBITED = "D"


class ContractError(ValueError):
    """A descriptor or port violates the FIL-001 contract."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _conditions(values: tuple[str, ...], code: str) -> tuple[str, ...]:
    for value in values:
        _require(bool(_CONDITION.match(value)), f"{code}:{value}")
    _require(len(set(values)) == len(values), f"{code}_DUPLICATE")
    return tuple(sorted(values))


@dataclass(frozen=True)
class PortSpec:
    """One typed input or output of a function.

    ``evidence_states`` on an output is every state an item on that port may
    carry; on an input it is every state the function admits.
    """

    name: str
    semantic_type: str
    evidence_states: tuple[str, ...]
    schema_ref: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        _require(bool(_CONDITION.match(self.name)), f"INVALID_PORT_NAME:{self.name}")
        _require(
            bool(_SEMANTIC_TYPE.match(self.semantic_type)),
            f"INVALID_SEMANTIC_TYPE:{self.semantic_type}",
        )
        _require(
            bool(self.evidence_states), f"PORT_EVIDENCE_STATES_REQUIRED:{self.name}"
        )
        unknown = sorted(set(self.evidence_states) - EVIDENCE_STATES)
        _require(not unknown, f"UNKNOWN_EVIDENCE_STATE:{','.join(unknown)}")
        object.__setattr__(
            self, "evidence_states", tuple(sorted(set(self.evidence_states)))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "semantic_type": self.semantic_type,
            "evidence_states": list(self.evidence_states),
            "schema_ref": self.schema_ref,
            "description": self.description,
        }


@dataclass(frozen=True)
class BudgetRequirement:
    """What one invocation may consume. FIL-001 descriptors default to zero spend."""

    provider_calls_max: int = 0
    cost_units_max: int = 1
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        _require(self.provider_calls_max >= 0, "NEGATIVE_PROVIDER_CALL_BUDGET")
        _require(self.cost_units_max >= 0, "NEGATIVE_COST_UNIT_BUDGET")
        _require(self.timeout_seconds > 0, "NON_POSITIVE_TIMEOUT")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_calls_max": self.provider_calls_max,
            "cost_units_max": self.cost_units_max,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class ProvenanceRequirement:
    """Whether a function needs, and whether it preserves, an upstream chain."""

    requires_upstream_chain: bool = True
    preserves_chain: bool = True
    requires_source_anchor: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "requires_upstream_chain": self.requires_upstream_chain,
            "preserves_chain": self.preserves_chain,
            "requires_source_anchor": self.requires_source_anchor,
        }


@dataclass(frozen=True)
class TaxonResolutionPolicy:
    """What a function guarantees or requires about taxon identity (FIL-001B).

    ``provides``: every taxon link the function emits names the backbone
    ``authority``, uses only :data:`TAXON_LINK_STATUSES`, and was matched
    exactly. ``requires``: the function admits only items whose taxon link has a
    status in ``admitted_statuses``; anything else must have been withheld
    upstream. Fuzzy matching is never permitted -- a fuzzy taxon match is a
    candidate for human review, not a resolution.
    """

    role: str
    authority: str = CANONICAL_TAXON_AUTHORITY
    admitted_statuses: tuple[str, ...] = TAXON_LINK_STATUSES
    fuzzy_matching_allowed: bool = False

    def __post_init__(self) -> None:
        _require(
            self.role in {"provides", "requires"},
            f"INVALID_TAXON_POLICY_ROLE:{self.role}",
        )
        _require(
            bool(_CONDITION.match(self.authority)),
            f"INVALID_TAXON_AUTHORITY:{self.authority}",
        )
        _require(not self.fuzzy_matching_allowed, "FUZZY_TAXON_MATCHING_FORBIDDEN")
        unknown = sorted(set(self.admitted_statuses) - set(TAXON_LINK_STATUSES))
        _require(not unknown, f"UNKNOWN_TAXON_LINK_STATUS:{','.join(unknown)}")
        _require(bool(self.admitted_statuses), "TAXON_POLICY_ADMITS_NOTHING")
        object.__setattr__(
            self, "admitted_statuses", tuple(sorted(set(self.admitted_statuses)))
        )

    @property
    def conditions(self) -> tuple[str, str]:
        """The conditions a provider establishes and a requirer depends on."""
        return ("taxon_resolution_recorded", f"taxon_authority_{self.authority}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "authority": self.authority,
            "admitted_statuses": list(self.admitted_statuses),
            "fuzzy_matching_allowed": self.fuzzy_matching_allowed,
        }


@dataclass(frozen=True)
class HealthSpec:
    """Declared status plus the failure reasons the function can report."""

    status: str
    evidence: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(
            self.status in CAPABILITY_STATUSES,
            f"UNKNOWN_CAPABILITY_STATUS:{self.status}",
        )
        for reason in self.failure_reasons:
            # Same pattern as the descriptor schema, so every accepted object
            # serializes to its declared schema.
            _require(
                bool(_REASON_CODE.match(reason)),
                f"INVALID_FAILURE_REASON:{reason}",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence": list(self.evidence),
            "failure_reasons": list(self.failure_reasons),
        }


@dataclass(frozen=True)
class CapabilityDescriptor:
    """OWL-S-style profile of one existing function: IOPE plus authority."""

    capability_id: str
    version: str
    operator_class: OperatorClass
    registry_capability: str
    summary: str
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]
    autonomy_class: AutonomyClass
    health: HealthSpec
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ("read_only_research",)
    budget: BudgetRequirement = field(default_factory=BudgetRequirement)
    provenance: ProvenanceRequirement = field(default_factory=ProvenanceRequirement)
    triggers: tuple[str, ...] = ()
    emits: tuple[str, ...] = ()
    implementation: str | None = None
    brain_capability_id: str | None = None
    taxon_resolution: TaxonResolutionPolicy | None = None

    def __post_init__(self) -> None:
        _require(
            bool(_ID.match(self.capability_id)),
            f"INVALID_CAPABILITY_ID:{self.capability_id}",
        )
        _require(bool(_SEMVER.match(self.version)), f"INVALID_VERSION:{self.version}")
        _require(
            isinstance(self.operator_class, OperatorClass), "INVALID_OPERATOR_CLASS"
        )
        _require(
            isinstance(self.autonomy_class, AutonomyClass), "INVALID_AUTONOMY_CLASS"
        )
        _require(bool(self.summary.strip()), "SUMMARY_REQUIRED")
        # Raises CapabilityUnknown -- the routing registry's own refusal -- rather
        # than letting FIL invent a capability nobody has classified.
        provider_required = is_provider_capability(self.registry_capability)
        _require(
            bool(self.inputs) and bool(self.outputs), "INPUTS_AND_OUTPUTS_REQUIRED"
        )
        for ports, code in (
            (self.inputs, "DUPLICATE_INPUT_PORT"),
            (self.outputs, "DUPLICATE_OUTPUT_PORT"),
        ):
            names = [port.name for port in ports]
            _require(len(set(names)) == len(names), code)
        object.__setattr__(
            self,
            "preconditions",
            _conditions(self.preconditions, "INVALID_PRECONDITION"),
        )
        object.__setattr__(self, "effects", _conditions(self.effects, "INVALID_EFFECT"))
        forbidden = sorted(set(self.effects) & FORBIDDEN_EFFECTS)
        _require(not forbidden, f"FORBIDDEN_EFFECT:{','.join(forbidden)}")
        for port in self.outputs:
            claimed = sorted(set(port.evidence_states) & HUMAN_ONLY_EVIDENCE_STATES)
            _require(
                not claimed,
                f"HUMAN_ONLY_EVIDENCE_STATE_ON_OUTPUT:{port.name}:{','.join(claimed)}",
            )

        _require(bool(self.permissions), "PERMISSIONS_REQUIRED")
        _require(
            len(set(self.permissions)) == len(self.permissions), "DUPLICATE_PERMISSION"
        )
        object.__setattr__(self, "permissions", tuple(sorted(self.permissions)))
        prohibited = set(self.permissions) & PROHIBITED_CAPABILITIES
        if self.autonomy_class is AutonomyClass.SAFE_AUTONOMOUS:
            outside = sorted(set(self.permissions) - SAFE_AUTONOMOUS_PERMISSIONS)
            _require(not outside, f"CLASS_A_PERMISSION_NOT_SAFE:{','.join(outside)}")
        if prohibited:
            _require(
                self.autonomy_class
                in {AutonomyClass.HUMAN_APPROVAL, AutonomyClass.PROHIBITED},
                f"PROHIBITED_PERMISSION_REQUIRES_CLASS_B_OR_D:{','.join(sorted(prohibited))}",
            )

        if provider_required:
            _require(
                self.budget.provider_calls_max > 0,
                "PROVIDER_CAPABILITY_NEEDS_PROVIDER_BUDGET",
            )
            _require(
                self.autonomy_class is not AutonomyClass.SAFE_AUTONOMOUS,
                "PROVIDER_CAPABILITY_CANNOT_BE_CLASS_A",
            )
        else:
            _require(
                self.budget.provider_calls_max == 0,
                "DETERMINISTIC_CAPABILITY_HAS_PROVIDER_BUDGET",
            )

        if self.taxon_resolution is not None:
            needed = set(self.taxon_resolution.conditions)
            declared = set(
                self.effects
                if self.taxon_resolution.role == "provides"
                else self.preconditions
            )
            missing = sorted(needed - declared)
            _require(
                not missing,
                f"TAXON_POLICY_CONDITIONS_UNDECLARED:{self.taxon_resolution.role}:{','.join(missing)}",
            )

        # The authority condition is reserved: only a declared provider may
        # establish it. Every requirer needs it, so a policy-less function cannot
        # satisfy a requirer's preconditions.
        reserved = sorted(
            effect for effect in self.effects if effect.startswith("taxon_authority_")
        )
        if reserved:
            _require(
                self.taxon_resolution is not None
                and self.taxon_resolution.role == "provides",
                f"TAXON_CONDITION_WITHOUT_PROVIDER_POLICY:{','.join(reserved)}",
            )

        known_events = {item.value for item in ObservationEventType}
        for name, values in (("TRIGGER", self.triggers), ("EMITTED_EVENT", self.emits)):
            unknown = sorted(set(values) - known_events)
            _require(not unknown, f"UNKNOWN_{name}:{','.join(unknown)}")
        object.__setattr__(self, "triggers", tuple(sorted(set(self.triggers))))
        object.__setattr__(self, "emits", tuple(sorted(set(self.emits))))

    @property
    def provider_required(self) -> bool:
        return CAPABILITIES[self.registry_capability].provider_required

    def input(self, name: str) -> PortSpec:
        return _port(self.inputs, name, "UNKNOWN_INPUT_PORT")

    def output(self, name: str) -> PortSpec:
        return _port(self.outputs, name, "UNKNOWN_OUTPUT_PORT")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DESCRIPTOR_SCHEMA,
            "capability_id": self.capability_id,
            "version": self.version,
            "operator_class": self.operator_class.value,
            "registry_capability": self.registry_capability,
            "provider_required": self.provider_required,
            "brain_capability_id": self.brain_capability_id,
            "summary": self.summary,
            "implementation": self.implementation,
            "inputs": [port.to_dict() for port in self.inputs],
            "outputs": [port.to_dict() for port in self.outputs],
            "preconditions": list(self.preconditions),
            "effects": list(self.effects),
            "permissions": list(self.permissions),
            "autonomy_class": self.autonomy_class.value,
            "budget": self.budget.to_dict(),
            "provenance": self.provenance.to_dict(),
            "triggers": list(self.triggers),
            "emits": list(self.emits),
            "health": self.health.to_dict(),
            "taxon_resolution": self.taxon_resolution.to_dict()
            if self.taxon_resolution
            else None,
        }


def _port(ports: tuple[PortSpec, ...], name: str, code: str) -> PortSpec:
    for port in ports:
        if port.name == name:
            return port
    raise ContractError(f"{code}:{name}")
