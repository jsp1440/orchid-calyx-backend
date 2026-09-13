from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .models import StrategyDecisionState, stable_fingerprint


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

    def to_fingerprint_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "task_class_id": self.task_class_id,
            "risk_class": self.risk_class,
            "observation": self.observation,
            "evidence_refs": self.evidence_refs,
            "material_fingerprint": self.material_fingerprint,
            "measured_metric": self.measured_metric,
            "measured_value": self.measured_value,
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


@dataclass(slots=True)
class ImprovementDiscoveryEngine:
    policy_version: str = "oc-rsi-001.v1"

    def classify_eligibility(
        self,
        signal: ImprovementSignal,
        hypothesis: ImprovementHypothesis,
        prior_outcomes: Iterable[PriorImprovementOutcome] = (),
    ) -> ImprovementEligibility:
        for outcome in prior_outcomes:
            same_material = (
                outcome.signal_material_fingerprint == signal.material_fingerprint
            )
            if outcome.hypothesis_fingerprint == hypothesis.fingerprint and same_material:
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

        if signal.measured_metric and signal.measured_value is None:
            return ImprovementEligibility.UNMEASURED

        return ImprovementEligibility.ELIGIBLE

    def build_queue_packet(
        self,
        signal: ImprovementSignal,
        hypothesis: ImprovementHypothesis,
        *,
        priority: str = "oc-p1",
    ) -> ImprovementQueuePacket:
        eligibility = self.classify_eligibility(signal, hypothesis)
        if eligibility not in {
            ImprovementEligibility.ELIGIBLE,
            ImprovementEligibility.REQUIRES_OWNER,
            ImprovementEligibility.UNMEASURED,
        }:
            raise ValueError(f"suppressed hypothesis cannot be queued: {eligibility}")

        owner_gate = eligibility == ImprovementEligibility.REQUIRES_OWNER
        labels = ("oc-queued", priority)
        capability = "improvement:bounded-hypothesis:v1"
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
- owner approval required: `{str(owner_gate).lower()}`

## Bounded evaluation plan
{plan}

## Evidence
{evidence}

## Guardrails
This packet is discovery output only. Execution must remain on the canonical DeepOrchestrate/`oc-queued` path. OC-EVALS baseline/candidate evidence is required before promotion. No merge, deploy, provider activation/spend, production scientific/taxonomic/KG mutation, credential/security change, protected-locality exposure, or publication is authorized by this packet.

`OC-QUEUE-CAPABILITY: {capability}`
"""
        return ImprovementQueuePacket(
            title=f"P1 RSI hypothesis — {hypothesis.hypothesis_id}",
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
        return {
            "schema": "oc.improvement-discovery-memory.v1",
            "policy_version": self.policy_version,
            "signal_fingerprint": signal.fingerprint,
            "signal_material_fingerprint": signal.material_fingerprint,
            "hypothesis_fingerprint": hypothesis.fingerprint,
            "task_class_id": hypothesis.task_class_id,
            "risk_class": hypothesis.risk_class,
            "eligibility": eligibility,
            "primary_metric": hypothesis.primary_metric,
            "evidence_refs": hypothesis.evidence_refs,
            "rollback_strategy_fingerprint": hypothesis.rollback_strategy_fingerprint,
        }


def material_change_fingerprint(payload: dict[str, Any]) -> str:
    return stable_fingerprint(payload)
