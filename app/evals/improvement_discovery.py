from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .models import (
    MeasurementState,
    MetricValue,
    StrategyDecisionState,
    canonical_json,
    stable_fingerprint,
)


class ImprovementSignalSource(StrEnum):
    EVALUATION = "EVALUATION"
    SCIENTIFIC_MEMORY = "SCIENTIFIC_MEMORY"
    WORKFLOW = "WORKFLOW"
    TELEMETRY = "TELEMETRY"
    INNOVATION = "INNOVATION"


class ImprovementEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"
    SUPPRESSED_NO_BENEFIT = "SUPPRESSED_NO_BENEFIT"
    REQUIRES_OWNER = "REQUIRES_OWNER"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True, slots=True)
class ImprovementSignal:
    signal_id: str
    version: str
    source: ImprovementSignalSource
    task_class_id: str
    risk_class: str
    observation: str
    evidence_refs: tuple[str, ...]
    material_fingerprint: str
    measured_metric: str | None = None
    measured_value: float | int | None = None
    desired_direction: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    measurement_state: MeasurementState | None = None

    def __post_init__(self) -> None:
        state = self.measurement_state
        if state is None:
            state = (
                MeasurementState.MEASURED
                if self.measured_value is not None
                else MeasurementState.UNKNOWN
            )
        state = MeasurementState(state)
        MetricValue(state, self.measured_value)
        if self.measured_value is not None:
            if isinstance(self.measured_value, bool) or not math.isfinite(
                self.measured_value
            ):
                raise ValueError("measurement must be a finite numeric value")
            if not self.measured_metric:
                raise ValueError("measured value requires a metric identity")
        object.__setattr__(self, "measurement_state", state)

    def to_fingerprint_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "task_class_id": self.task_class_id,
            "risk_class": self.risk_class,
            "observation": self.observation,
            "evidence_refs": self.evidence_refs,
            "material_fingerprint": self.material_fingerprint,
            "measured_metric": self.measured_metric,
            "measured_value": self.measured_value,
            "measurement_state": self.measurement_state,
            "desired_direction": self.desired_direction,
        }

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class ImprovementHypothesis:
    hypothesis_id: str
    version: str
    signal_fingerprint: str
    task_class_id: str
    risk_class: str
    proposed_change: str
    expected_effect: str
    primary_metric: str
    baseline_strategy_fingerprint: str
    candidate_strategy_ref: str
    rollback_strategy_fingerprint: str
    evaluation_plan: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    material_fingerprint: str
    owner_approval_required: bool = False

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)

    @property
    def candidate_material_fingerprint(self) -> str:
        """Ignore editorial changes when identifying an unchanged strategy."""
        return stable_fingerprint(
            {
                "task_class_id": self.task_class_id,
                "baseline": self.baseline_strategy_fingerprint,
                "candidate": self.candidate_strategy_ref,
                "material": self.material_fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class ImprovementQueuePacket:
    title: str
    body: str
    labels: tuple[str, ...]
    capability: str
    hypothesis_fingerprint: str
    requires_evaluation: bool = True
    auto_promotable: bool = False


@dataclass(frozen=True, slots=True)
class PriorImprovementOutcome:
    hypothesis_fingerprint: str
    signal_material_fingerprint: str
    decision_state: StrategyDecisionState
    candidate_material_fingerprint: str | None = None


@dataclass(slots=True)
class ImprovementDiscoveryEngine:
    policy_version: str = "oc-rsi-001.v2"

    @staticmethod
    def _validate_lineage(
        signal: ImprovementSignal, hypothesis: ImprovementHypothesis
    ) -> None:
        if hypothesis.signal_fingerprint != signal.fingerprint:
            raise ValueError("hypothesis signal fingerprint mismatch")
        for field_name in ("task_class_id", "risk_class", "material_fingerprint"):
            if getattr(hypothesis, field_name) != getattr(signal, field_name):
                raise ValueError(f"hypothesis {field_name} mismatch")
        if signal.risk_class.lower() not in {
            "low",
            "medium",
            "moderate",
            "high",
            "critical",
        }:
            raise ValueError("unknown risk class")
        for field_name in (
            "hypothesis_id",
            "version",
            "task_class_id",
            "material_fingerprint",
            "proposed_change",
            "expected_effect",
            "primary_metric",
            "baseline_strategy_fingerprint",
            "candidate_strategy_ref",
            "rollback_strategy_fingerprint",
        ):
            if not getattr(hypothesis, field_name).strip():
                raise ValueError(f"hypothesis {field_name} is required")
        if (
            hypothesis.rollback_strategy_fingerprint
            != hypothesis.baseline_strategy_fingerprint
        ):
            raise ValueError("rollback must retain the previous baseline strategy")
        if not hypothesis.evaluation_plan or not all(
            step.strip() for step in hypothesis.evaluation_plan
        ):
            raise ValueError("bounded evaluation plan is required")
        if not signal.evidence_refs or not hypothesis.evidence_refs:
            raise ValueError("signal and hypothesis evidence is required")

    def classify_eligibility(
        self,
        signal: ImprovementSignal,
        hypothesis: ImprovementHypothesis,
        prior_outcomes: Iterable[PriorImprovementOutcome] = (),
    ) -> ImprovementEligibility:
        self._validate_lineage(signal, hypothesis)
        for outcome in prior_outcomes:
            same_material = (
                outcome.signal_material_fingerprint == signal.material_fingerprint
            )
            same_candidate = (
                outcome.candidate_material_fingerprint
                == hypothesis.candidate_material_fingerprint
                if outcome.candidate_material_fingerprint
                else outcome.hypothesis_fingerprint == hypothesis.fingerprint
            )
            if same_candidate and same_material:
                if outcome.decision_state in {
                    StrategyDecisionState.KEEP_BASELINE,
                    StrategyDecisionState.REJECT_QUALITY,
                    StrategyDecisionState.REJECT_SAFETY,
                    StrategyDecisionState.REJECT_COST,
                    StrategyDecisionState.REJECT_INSTABILITY,
                }:
                    return ImprovementEligibility.SUPPRESSED_NO_BENEFIT
                return ImprovementEligibility.SUPPRESSED_DUPLICATE

        if hypothesis.owner_approval_required or signal.risk_class.lower() in {
            "high",
            "critical",
        }:
            return ImprovementEligibility.REQUIRES_OWNER

        if (
            signal.measured_metric
            and signal.measurement_state != MeasurementState.MEASURED
        ):
            return ImprovementEligibility.UNMEASURED

        return ImprovementEligibility.ELIGIBLE

    def build_queue_packet(
        self,
        signal: ImprovementSignal,
        hypothesis: ImprovementHypothesis,
        *,
        priority: str = "oc-p1",
        prior_outcomes: Iterable[PriorImprovementOutcome] = (),
        dependency_issues: tuple[int, ...] = (),
    ) -> ImprovementQueuePacket:
        eligibility = self.classify_eligibility(signal, hypothesis, prior_outcomes)
        if eligibility not in {
            ImprovementEligibility.ELIGIBLE,
            ImprovementEligibility.REQUIRES_OWNER,
            ImprovementEligibility.UNMEASURED,
        }:
            raise ValueError(f"suppressed hypothesis cannot be queued: {eligibility}")

        if priority not in {"oc-p0", "oc-p1", "oc-p2", "oc-p3", "oc-p4"}:
            raise ValueError("unsupported canonical queue priority")
        owner_gate = eligibility == ImprovementEligibility.REQUIRES_OWNER
        labels = ("oc-blocked" if owner_gate else "oc-queued", priority)
        capability = f"improvement:bounded-hypothesis:{hypothesis.candidate_material_fingerprint}:v1"
        if any(type(number) is not int or number < 1 for number in dependency_issues):
            raise ValueError("dependency issue identities must be positive integers")
        dependency_marker = (
            "OC-SWARM-DEPENDS-ON: "
            + ", ".join(f"#{number}" for number in sorted(set(dependency_issues)))
            + "\n"
            if dependency_issues
            else ""
        )
        evidence = "\n".join(f"- {ref}" for ref in hypothesis.evidence_refs) or "- none"
        plan = "\n".join(f"- {step}" for step in hypothesis.evaluation_plan)

        body = f"""## Improvement hypothesis
{hypothesis.proposed_change}

## Expected measurable effect
{hypothesis.expected_effect}

## Evaluation contract
- task class: `{hypothesis.task_class_id}`
- primary metric: `{hypothesis.primary_metric}`
- baseline strategy: `{hypothesis.baseline_strategy_fingerprint}`
- candidate strategy ref: `{hypothesis.candidate_strategy_ref}`
- rollback strategy: `{hypothesis.rollback_strategy_fingerprint}`
- discovery policy: `{self.policy_version}`
- signal fingerprint: `{signal.fingerprint}`
- hypothesis fingerprint: `{hypothesis.fingerprint}`
- eligibility: `{eligibility}`
- measurement state: `{signal.measurement_state}`
- owner approval required: `{str(owner_gate).lower()}`

## Bounded evaluation plan
{plan}

## Evidence
{evidence}

## Guardrails
This packet is discovery output only. Execution must remain on the canonical DeepOrchestrate/`oc-queued` path. OC-EVALS baseline/candidate evidence is required before promotion. No merge, deploy, provider activation/spend, production scientific/taxonomic/KG mutation, credential/security change, protected-locality exposure, or publication is authorized by this packet.

OC-QUEUE-CAPABILITY: {capability}
OC-SWARM-READS: provenance
OC-SWARM-WRITES: control-plane, scientific-memory
{dependency_marker}
"""
        return ImprovementQueuePacket(
            title=f"{priority.removeprefix('oc-').upper()} RSI hypothesis — {hypothesis.hypothesis_id}",
            body=body,
            labels=labels,
            capability=capability,
            hypothesis_fingerprint=hypothesis.fingerprint,
            requires_evaluation=True,
            auto_promotable=False,
        )

    def scientific_memory_summary(
        self,
        signal: ImprovementSignal,
        hypothesis: ImprovementHypothesis,
        eligibility: ImprovementEligibility,
    ) -> dict[str, Any]:
        self._validate_lineage(signal, hypothesis)
        return {
            "schema": "oc.improvement-discovery-memory.v1",
            "policy_version": self.policy_version,
            "signal_fingerprint": signal.fingerprint,
            "signal_material_fingerprint": signal.material_fingerprint,
            "hypothesis_fingerprint": hypothesis.fingerprint,
            "candidate_material_fingerprint": hypothesis.candidate_material_fingerprint,
            "task_class_id": hypothesis.task_class_id,
            "risk_class": hypothesis.risk_class,
            "eligibility": eligibility,
            "primary_metric": hypothesis.primary_metric,
            "measurement": {
                "state": signal.measurement_state.value,
                "value": signal.measured_value,
            },
            "evidence_refs": hypothesis.evidence_refs,
            "rollback_strategy_fingerprint": hypothesis.rollback_strategy_fingerprint,
        }


def material_change_fingerprint(payload: dict[str, Any]) -> str:
    return stable_fingerprint(canonical_json(payload))
