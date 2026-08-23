"""Versioned contracts for the Calyx improvement flywheel (#1138, packet 1).

Contracts and validation only. Nothing here persists, publishes, or writes to
the graph — later packets do that, and they inherit these guarantees rather
than re-deriving them.

THE RULE THIS MODULE EXISTS TO ENFORCE

A model that can cite itself can manufacture consensus. Given one fluent
statement, a system with no self-evidence rule will happily produce a second
statement supported by the first, a third supported by the second, and a
confidence figure that rises with every step while no new observation has
entered the record. Everything downstream — review queues, knowledge
suggestions, published claims — inherits that fabrication and cannot detect it,
because each individual link looked well-formed.

So a Calyx-generated assertion must rest on at least one non-Calyx source, and
no assertion may cite itself. Both are enforced at construction: an invalid
assertion cannot be built, let alone stored.

WHAT DETERMINISTIC CONTROL MEANS HERE

A natural-language step may *propose* work. It never owns permission,
branching, escalation, graph writes, or termination — those live in
`StepControl`, which is plain data a deterministic executor reads. A step whose
prose says "then publish this" changes nothing, because publication is not a
field prose can set.

Every proposed graph mutation defaults to provisional and not publishable. The
defaults are the safe values, so an incomplete caller produces a governed
record rather than an ungoverned one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.calyx_flywheel.locality import assert_no_sensitive_locality

__all__ = [
    "AssertionKind",
    "AssertionOrigin",
    "GovernanceState",
    "KnowledgeSuggestion",
    "ModelIdentity",
    "Procedure",
    "ProcedureStep",
    "ProvenanceAnchor",
    "ReviewDecision",
    "ReviewOutcome",
    "ScientificAssertion",
    "SimulationCase",
    "SimulationRun",
    "StepControl",
    "SupersessionRecord",
]

CONTRACT_VERSION = "calyx-flywheel/1"

_SHA256_LENGTH = 64


class AssertionKind(StrEnum):
    """What kind of statement this is.

    These are not interchangeable. An OBSERVATION is something someone
    recorded; a HYPOTHESIS is something nobody has established. Collapsing them
    is how a proposal becomes a finding, so the kind is required and has no
    default.
    """

    OBSERVATION = "OBSERVATION"
    EXTRACTED_CLAIM = "EXTRACTED_CLAIM"
    SYNTHESIS = "SYNTHESIS"
    HYPOTHESIS = "HYPOTHESIS"
    CONCLUSION = "CONCLUSION"


class AssertionOrigin(StrEnum):
    """Who produced the statement. Load-bearing for the self-evidence rule."""

    CALYX_GENERATED = "CALYX_GENERATED"
    HUMAN_AUTHORED = "HUMAN_AUTHORED"
    LITERATURE_EXTRACTED = "LITERATURE_EXTRACTED"
    INSTRUMENT_RECORDED = "INSTRUMENT_RECORDED"
    EXTERNAL_DATASET = "EXTERNAL_DATASET"


#: Origins that count as evidence independent of Calyx.
NON_CALYX_ORIGINS: frozenset[AssertionOrigin] = frozenset(
    {
        AssertionOrigin.HUMAN_AUTHORED,
        AssertionOrigin.LITERATURE_EXTRACTED,
        AssertionOrigin.INSTRUMENT_RECORDED,
        AssertionOrigin.EXTERNAL_DATASET,
    }
)


class GovernanceState(StrEnum):
    """Where a record stands with respect to human review."""

    PROVISIONAL = "PROVISIONAL"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class ReviewOutcome(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"
    SUPERSEDE = "SUPERSEDE"
    RETRACT = "RETRACT"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_text(value: str, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    return text


def _require_hash(value: str, code: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(code)
    return digest


@dataclass(frozen=True)
class ProvenanceAnchor:
    """Where a statement came from, precisely enough to go back and check.

    A source id without a content hash is not provenance: the document it names
    may have changed since, and nothing would reveal that. Both are required.
    """

    source_kind: str
    source_id: str
    content_hash: str
    revision_id: str | None = None
    anchor_id: str | None = None
    retrieved_at: datetime = field(default_factory=_utc_now)
    locator: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", _require_text(self.source_kind, "PROVENANCE_SOURCE_KIND_REQUIRED"))
        object.__setattr__(self, "source_id", _require_text(self.source_id, "PROVENANCE_SOURCE_ID_REQUIRED"))
        object.__setattr__(self, "content_hash", _require_hash(self.content_hash, "PROVENANCE_CONTENT_HASH_REQUIRED"))
        # A locator is free-form, which makes it the likeliest place for a
        # coordinate to arrive by accident.
        assert_no_sensitive_locality(dict(self.locator), path="locator")


@dataclass(frozen=True)
class ModelIdentity:
    """Which model and prompt produced a generated statement.

    Required on Calyx-generated assertions. A generated claim whose model and
    prompt version are unknown cannot be reproduced or retracted by cohort, so
    it cannot be governed.
    """

    model_id: str
    model_version: str
    prompt_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", _require_text(self.model_id, "MODEL_ID_REQUIRED"))
        object.__setattr__(self, "model_version", _require_text(self.model_version, "MODEL_VERSION_REQUIRED"))
        object.__setattr__(self, "prompt_version", _require_text(self.prompt_version, "PROMPT_VERSION_REQUIRED"))


@dataclass(frozen=True)
class SupersessionRecord:
    """One link in a statement's history. Kept, never overwritten."""

    superseded_assertion_id: str
    reason: str
    actor: str
    occurred_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "superseded_assertion_id", _require_text(self.superseded_assertion_id, "SUPERSEDED_ID_REQUIRED"))
        object.__setattr__(self, "reason", _require_text(self.reason, "SUPERSESSION_REASON_REQUIRED"))
        object.__setattr__(self, "actor", _require_text(self.actor, "SUPERSESSION_ACTOR_REQUIRED"))


@dataclass(frozen=True)
class ScientificAssertion:
    """One governed scientific statement.

    Construction is the gate. An assertion missing provenance, taxonomy
    version, model identity where required, or violating the self-evidence
    rule, cannot be built — so no downstream packet has to re-check it.
    """

    assertion_id: str
    kind: AssertionKind
    origin: AssertionOrigin
    statement: str
    taxonomy_version: str
    provenance: tuple[ProvenanceAnchor, ...]
    #: Assertion ids this rests on, paired with their origins so the
    #: self-evidence rule can be evaluated without a second lookup.
    supported_by: tuple[tuple[str, AssertionOrigin], ...] = ()
    counterevidence: tuple[str, ...] = ()
    confidence: float | None = None
    model: ModelIdentity | None = None
    governance_state: GovernanceState = GovernanceState.PROVISIONAL
    publishable: bool = False
    supersession_history: tuple[SupersessionRecord, ...] = ()
    created_at: datetime = field(default_factory=_utc_now)
    contract_version: str = CONTRACT_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "assertion_id", _require_text(self.assertion_id, "ASSERTION_ID_REQUIRED"))
        object.__setattr__(self, "statement", _require_text(self.statement, "ASSERTION_STATEMENT_REQUIRED"))
        object.__setattr__(self, "taxonomy_version", _require_text(self.taxonomy_version, "TAXONOMY_VERSION_REQUIRED"))

        if not self.provenance:
            raise ValueError("PROVENANCE_REQUIRED")

        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")

        if self.origin is AssertionOrigin.CALYX_GENERATED:
            if self.model is None:
                raise ValueError("MODEL_IDENTITY_REQUIRED_FOR_GENERATED_ASSERTION")
            # The rule. A generated statement resting only on other generated
            # statements is a loop that accumulates confidence without
            # observation.
            if not any(origin in NON_CALYX_ORIGINS for _, origin in self.supported_by) and not any(
                anchor.source_kind.strip().upper() != "CALYX" for anchor in self.provenance
            ):
                raise ValueError("CALYX_GENERATED_ASSERTION_REQUIRES_EXTERNAL_EVIDENCE")

        if any(reference == self.assertion_id for reference, _ in self.supported_by):
            raise ValueError("SELF_EVIDENCE_FORBIDDEN")
        if self.assertion_id in self.counterevidence:
            raise ValueError("SELF_COUNTEREVIDENCE_FORBIDDEN")

        # A publishable record cannot be one nobody has approved.
        if self.publishable and self.governance_state is not GovernanceState.APPROVED:
            raise ValueError("PUBLISHABLE_REQUIRES_APPROVAL")

        assert_no_sensitive_locality(dict(self.metadata), path="metadata")


@dataclass(frozen=True)
class StepControl:
    """The deterministic half of a procedure step.

    Prose proposes; this decides. Permissions, branching, escalation, graph
    writes and termination are all fields here, so a step's natural-language
    body cannot grant itself any of them however it is phrased.
    """

    may_write_graph: bool = False
    may_terminate: bool = False
    requires_human_escalation: bool = False
    allowed_next_step_ids: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.may_write_graph and not self.requires_human_escalation:
            # A graph write is the one action that changes shared scientific
            # state. It does not proceed without a human in the loop.
            raise ValueError("GRAPH_WRITE_REQUIRES_HUMAN_ESCALATION")


@dataclass(frozen=True)
class ProcedureStep:
    step_id: str
    description: str
    control: StepControl = field(default_factory=StepControl)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _require_text(self.step_id, "STEP_ID_REQUIRED"))
        object.__setattr__(self, "description", _require_text(self.description, "STEP_DESCRIPTION_REQUIRED"))


@dataclass(frozen=True)
class Procedure:
    procedure_id: str
    version: int
    title: str
    steps: tuple[ProcedureStep, ...]
    created_at: datetime = field(default_factory=_utc_now)
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "procedure_id", _require_text(self.procedure_id, "PROCEDURE_ID_REQUIRED"))
        object.__setattr__(self, "title", _require_text(self.title, "PROCEDURE_TITLE_REQUIRED"))
        if self.version < 1:
            raise ValueError("PROCEDURE_VERSION_INVALID")
        if not self.steps:
            raise ValueError("PROCEDURE_REQUIRES_STEPS")

        ids = [step.step_id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_STEP_ID")

        known = set(ids)
        for step in self.steps:
            for target in step.control.allowed_next_step_ids:
                if target not in known:
                    # A branch to a step that does not exist is an escape from
                    # the procedure, not a procedure.
                    raise ValueError("UNKNOWN_BRANCH_TARGET")


@dataclass(frozen=True)
class SimulationCase:
    case_id: str
    procedure_id: str
    procedure_version: int
    inputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _require_text(self.case_id, "CASE_ID_REQUIRED"))
        object.__setattr__(self, "procedure_id", _require_text(self.procedure_id, "PROCEDURE_ID_REQUIRED"))
        if self.procedure_version < 1:
            raise ValueError("PROCEDURE_VERSION_INVALID")
        assert_no_sensitive_locality(dict(self.inputs), path="inputs")


@dataclass(frozen=True)
class SimulationRun:
    """A simulation is a rehearsal. Its outputs are proposals, never findings."""

    run_id: str
    case_id: str
    started_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None
    produced_assertion_ids: tuple[str, ...] = ()
    governance_state: GovernanceState = GovernanceState.PROVISIONAL
    publishable: bool = False
    notes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _require_text(self.run_id, "RUN_ID_REQUIRED"))
        object.__setattr__(self, "case_id", _require_text(self.case_id, "CASE_ID_REQUIRED"))
        if self.publishable:
            # No simulation output is publishable. A rehearsal that could
            # publish is not a rehearsal.
            raise ValueError("SIMULATION_OUTPUT_NOT_PUBLISHABLE")
        assert_no_sensitive_locality(dict(self.notes), path="notes")


@dataclass(frozen=True)
class KnowledgeSuggestion:
    """A proposed graph mutation. Provisional and unpublishable by default."""

    suggestion_id: str
    assertion_id: str
    proposed_change: Mapping[str, Any]
    governance_state: GovernanceState = GovernanceState.PROVISIONAL
    publishable: bool = False
    created_at: datetime = field(default_factory=_utc_now)
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "suggestion_id", _require_text(self.suggestion_id, "SUGGESTION_ID_REQUIRED"))
        object.__setattr__(self, "assertion_id", _require_text(self.assertion_id, "ASSERTION_ID_REQUIRED"))
        if not self.proposed_change:
            raise ValueError("PROPOSED_CHANGE_REQUIRED")
        if self.publishable and self.governance_state is not GovernanceState.APPROVED:
            raise ValueError("PUBLISHABLE_REQUIRES_APPROVAL")
        assert_no_sensitive_locality(dict(self.proposed_change), path="proposed_change")


@dataclass(frozen=True)
class ReviewDecision:
    """A human decision. An abstention is recorded, never treated as approval."""

    decision_id: str
    subject_id: str
    outcome: ReviewOutcome
    reviewer: str
    rationale: str
    decided_at: datetime = field(default_factory=_utc_now)
    supersedes: SupersessionRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _require_text(self.decision_id, "DECISION_ID_REQUIRED"))
        object.__setattr__(self, "subject_id", _require_text(self.subject_id, "SUBJECT_ID_REQUIRED"))
        object.__setattr__(self, "reviewer", _require_text(self.reviewer, "REVIEWER_REQUIRED"))
        object.__setattr__(self, "rationale", _require_text(self.rationale, "REVIEW_RATIONALE_REQUIRED"))
        if self.outcome is ReviewOutcome.SUPERSEDE and self.supersedes is None:
            raise ValueError("SUPERSEDE_REQUIRES_SUPERSESSION_RECORD")

    @property
    def resulting_state(self) -> GovernanceState:
        """The state this decision produces.

        ABSTAIN deliberately leaves the subject under review. An abstention is
        the reviewer declining to decide, and reading it as approval is how an
        unreviewed claim acquires a reviewed appearance.
        """
        return {
            ReviewOutcome.APPROVE: GovernanceState.APPROVED,
            ReviewOutcome.REJECT: GovernanceState.REJECTED,
            ReviewOutcome.ABSTAIN: GovernanceState.UNDER_REVIEW,
            ReviewOutcome.SUPERSEDE: GovernanceState.SUPERSEDED,
            ReviewOutcome.RETRACT: GovernanceState.RETRACTED,
        }[self.outcome]
