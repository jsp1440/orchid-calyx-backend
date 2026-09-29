"""Evidence-bound bridge from intelligence items to the DeepOrchestrate reservoir.

A paper-discovery metadata signal must never directly become coding instructions.
This module enforces evidence gates before any TaskLeaf is admitted to the
DeepOrchestrate reservoir.  No second scheduler is introduced; the bridge delegates
entirely to the existing DeepOrchestrate queue identity, dependency gating, and
completion history.

Gates checked in order before admission:
  1. Item must exist in the intelligence ledger.
  2. Item lifecycle must not be \'DISCOVERED\' (raw metadata signal).
  3. Source findings and OC transfer hypotheses must be in separate fields.
  4. Material fingerprint must match computed sha256 of spec + sorted criteria.
  5. Prior terminal outcome for the same fingerprint suppresses unchanged rediscovery.

Outcomes are recorded back to intelligence_events so the full measured-benefit /
no-benefit / unmeasured history is preserved alongside issue and PR lineage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)

from .technology_scout import TRIAGE_DIMENSIONS

BRIDGE_VERSION = "oc.intelligence-bridge.v1"

_ADMITTED_LIFECYCLES = frozenset(
    {"ASSESSED", "UNDER_REVIEW", "PUBLISHED", "TRIAGED"}
)

_TERMINAL_OUTCOMES = frozenset(
    {
        "MEASURED_BENEFIT",
        "NO_BENEFIT",
        "FAILED",
        "BLOCKED",
        "SUPERSEDED",
        "REJECTED",
    }
)

_SUPPRESSING_RESERVOIR_STATES = frozenset({TaskState.COMPLETED, TaskState.BLOCKED})


class TriageDimensionAssessment(BaseModel):
    """One triage dimension with an evidence-based state."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["SCORED", "EXPLICITLY_UNASSESSED"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _score_consistency(self) -> TriageDimensionAssessment:
        if self.state == "SCORED" and self.score is None:
            raise ValueError("score is required when state is SCORED")
        if self.state == "EXPLICITLY_UNASSESSED" and self.score is not None:
            raise ValueError("score must be null when state is EXPLICITLY_UNASSESSED")
        return self


def _compute_fingerprint(specification: str, acceptance_criteria: list[str]) -> str:
    """Deterministic sha256 over the bounded implementation specification."""
    payload = {
        "specification": specification,
        "acceptance_criteria": sorted(acceptance_criteria),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class EvidenceGate(BaseModel):
    """Complete evidence package required before an intelligence item may become a TaskLeaf."""

    model_config = ConfigDict(extra="forbid")

    primary_source_version: str = Field(min_length=1, max_length=100)
    primary_source_assessment: str = Field(min_length=10, max_length=5000)
    architectural_overlap_comparison: str = Field(min_length=10, max_length=5000)
    implementation_specification: str = Field(min_length=10, max_length=5000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    github_issue_number: int = Field(ge=1)
    material_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependencies: list[str] = Field(default_factory=list, max_length=50)
    resource_claims: list[str] = Field(default_factory=list, max_length=20)
    triage_assessment: dict[str, TriageDimensionAssessment]
    priority: int = Field(default=Priority.P2, ge=0, le=4)
    authority_class: str = Field(default=AUTH_WORKSPACE)
    consequence_risk: Literal["low", "medium", "high"] = "low"
    estimated_size: Literal["xs", "s", "m", "l", "xl"] = "m"
    repo: str = Field(default="orchid-calyx-backend", min_length=1)
    module: str = Field(default="app", min_length=1)

    @model_validator(mode="after")
    def _triage_completeness(self) -> EvidenceGate:
        missing = [d for d in TRIAGE_DIMENSIONS if d not in self.triage_assessment]
        if missing:
            raise ValueError(
                f"Missing required triage dimensions: {missing}. "
                "All twelve dimensions must be explicitly assessed."
            )
        return self

    @property
    def computed_fingerprint(self) -> str:
        return _compute_fingerprint(
            self.implementation_specification, list(self.acceptance_criteria)
        )

    @property
    def task_key(self) -> str:
        return f"lit-intel:gh#{self.github_issue_number}:{self.material_fingerprint[:16]}"


@dataclass(frozen=True)
class GateRejection:
    """Describes why a task proposal was rejected at the evidence gate."""

    gate: str
    reason: str
    item_id: int
    material_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": False,
            "gate": self.gate,
            "reason": self.reason,
            "item_id": self.item_id,
            "material_fingerprint": self.material_fingerprint,
        }


@dataclass
class EvidenceRecord:
    """Outcome measurement for an admitted task."""

    issue_number: int
    evaluator: str
    outcome: Literal[
        "MEASURED_BENEFIT",
        "NO_BENEFIT",
        "UNMEASURED",
        "FAILED",
        "BLOCKED",
        "SUPERSEDED",
    ]
    outcome_notes: str
    pr_number: int | None = None
    benefit_metric: str | None = None


class ProposeTaskRequest(BaseModel):
    """Request body for POST /api/intake/intelligence/propose-task."""

    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(ge=1)
    assessor: str = Field(min_length=1, max_length=200)
    gate: EvidenceGate


class IntelligenceBridge:
    """Evidence-gated bridge from intelligence items to the DeepOrchestrate reservoir."""

    def __init__(self, *, reservoir: DeepOrchestrate | None = None) -> None:
        self._reservoir = reservoir if reservoir is not None else _get_default_reservoir()
        self._suppressed: set[str] = set()

    def propose_task(
        self,
        *,
        item_id: int,
        gate: EvidenceGate,
        assessor: str,
        get_item: Callable[[int], dict[str, Any] | None] | None = None,
    ) -> TaskLeaf | GateRejection:
        """Validate all evidence gates and register a TaskLeaf in the reservoir."""
        fetch = get_item if get_item is not None else _default_get_item

        item = fetch(item_id)
        if item is None:
            return GateRejection(
                gate="ITEM_NOT_FOUND",
                reason=f"Intelligence item {item_id} does not exist.",
                item_id=item_id,
            )

        lifecycle = str(item.get("lifecycle", ""))
        if lifecycle not in _ADMITTED_LIFECYCLES:
            return GateRejection(
                gate="LIFECYCLE_NOT_ASSESSED",
                reason=(
                    f"Item {item_id} has lifecycle \'{lifecycle}\'. "
                    "Only items that have passed primary-source review may be admitted "
                    "as engineering tasks. \'DISCOVERED\' means metadata-only status."
                ),
                item_id=item_id,
                material_fingerprint=gate.material_fingerprint,
            )

        if gate.primary_source_assessment.strip() == gate.architectural_overlap_comparison.strip():
            return GateRejection(
                gate="FINDINGS_NOT_SEPARATED",
                reason=(
                    "primary_source_assessment and architectural_overlap_comparison "
                    "must differ. Source findings and OC transfer hypotheses must "
                    "remain in separate fields."
                ),
                item_id=item_id,
                material_fingerprint=gate.material_fingerprint,
            )

        computed = gate.computed_fingerprint
        if gate.material_fingerprint != computed:
            return GateRejection(
                gate="FINGERPRINT_MISMATCH",
                reason=(
                    f"Provided fingerprint \'{gate.material_fingerprint[:16]}...\' does not "
                    f"match computed fingerprint \'{computed[:16]}...\'. "
                    "Specification or acceptance criteria may have been modified."
                ),
                item_id=item_id,
                material_fingerprint=gate.material_fingerprint,
            )

        if gate.material_fingerprint in self._suppressed:
            return GateRejection(
                gate="PRIOR_TERMINAL_OUTCOME",
                reason=(
                    "A prior completed, rejected, failed-benefit, blocked, or superseded "
                    f"outcome exists for fingerprint \'{gate.material_fingerprint[:16]}...\'. "
                    "Identical rediscovery is suppressed."
                ),
                item_id=item_id,
                material_fingerprint=gate.material_fingerprint,
            )

        task_key = gate.task_key
        existing = self._reservoir.get(task_key)
        if existing is not None:
            if existing.state in _SUPPRESSING_RESERVOIR_STATES:
                return GateRejection(
                    gate="PRIOR_TERMINAL_OUTCOME",
                    reason=(
                        f"Task \'{task_key}\' already exists in the reservoir with "
                        f"terminal state \'{existing.state}\'. "
                        "Unchanged rediscovery is suppressed."
                    ),
                    item_id=item_id,
                    material_fingerprint=gate.material_fingerprint,
                )
            return existing

        item_title = item.get("title", "Untitled intelligence task")
        leaf = TaskLeaf(
            key=task_key,
            title=f"GH#{gate.github_issue_number}: {item_title}",
            repo=gate.repo,
            module=gate.module,
            priority=gate.priority,
            authority_class=gate.authority_class,
            consequence_risk=gate.consequence_risk,
            estimated_size=gate.estimated_size,
            dependencies=list(gate.dependencies),
            acceptance_criteria=list(gate.acceptance_criteria),
            resources=list(gate.resource_claims),
            issue_number=gate.github_issue_number,
            evidence={
                "bridge_version": BRIDGE_VERSION,
                "assessor": assessor,
                "material_fingerprint": gate.material_fingerprint,
                "primary_source_version": gate.primary_source_version,
                "intelligence_item_id": item_id,
                "assessed_triage_dimensions": len(gate.triage_assessment),
            },
        )
        self._reservoir.register(leaf)
        return leaf

    def record_outcome(
        self,
        *,
        item_id: int,
        task_key: str,
        evidence: EvidenceRecord,
        material_fingerprint: str,
        record_event: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Record a measured outcome and suppress future rediscovery if terminal."""
        outcome = evidence.outcome
        is_terminal = outcome in _TERMINAL_OUTCOMES
        if is_terminal:
            self._suppressed.add(material_fingerprint)

        event_payload: dict[str, Any] = {
            "task_key": task_key,
            "outcome": outcome,
            "issue_number": evidence.issue_number,
            "pr_number": evidence.pr_number,
            "evaluator": evidence.evaluator,
            "outcome_notes": evidence.outcome_notes,
            "benefit_metric": evidence.benefit_metric,
            "bridge_version": BRIDGE_VERSION,
        }

        if record_event is not None:
            record_event(
                item_id=item_id,
                event_type="TASK_OUTCOME",
                event_payload=event_payload,
            )

        return {
            "item_id": item_id,
            "task_key": task_key,
            "outcome": outcome,
            "suppressed_future_rediscovery": is_terminal,
            "event_payload": event_payload,
            "canonical_graph_mutated": False,
        }

    def suppress_fingerprint(self, material_fingerprint: str) -> None:
        """Directly add a fingerprint to the suppression set."""
        self._suppressed.add(material_fingerprint)

    def is_suppressed(self, material_fingerprint: str) -> bool:
        """Return True if the fingerprint has a terminal outcome on record."""
        return material_fingerprint in self._suppressed


_default_reservoir_instance: DeepOrchestrate | None = None


def _get_default_reservoir() -> DeepOrchestrate:
    global _default_reservoir_instance
    if _default_reservoir_instance is None:
        _default_reservoir_instance = DeepOrchestrate(configured_width=5)
    return _default_reservoir_instance


def _default_get_item(item_id: int) -> dict[str, Any] | None:
    from .intelligence_repository import get_intelligence_item

    return get_intelligence_item(item_id)


bridge = IntelligenceBridge()
