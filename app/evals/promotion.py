from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .models import (
    EvaluationResult,
    EvaluationTaskClass,
    MeasurementState,
    StrategyDecision,
    StrategyDecisionState,
    StrategySpec,
    stable_fingerprint,
)


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    version: str = "1"
    minimum_primary_score: float = 0.0
    minimum_absolute_improvement: float = 0.0
    equivalent_quality_tolerance: float = 0.0
    minimum_cost_reduction_ratio: float = 0.0
    minimum_latency_reduction_ratio: float = 0.0
    high_risk_classes: tuple[str, ...] = ("high", "critical")


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    baseline_results: tuple[EvaluationResult, ...]
    candidate_results: tuple[EvaluationResult, ...]
    evaluator_set_fingerprint: str
    case_fingerprints: tuple[str, ...] = ()
    issue_refs: tuple[str, ...] = ()
    pr_refs: tuple[str, ...] = ()
    commit_shas: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(
            {
                "baseline": [result.fingerprint for result in self.baseline_results],
                "candidate": [result.fingerprint for result in self.candidate_results],
                "evaluator_set_fingerprint": self.evaluator_set_fingerprint,
                "case_fingerprints": self.case_fingerprints,
                "issue_refs": self.issue_refs,
                "pr_refs": self.pr_refs,
                "commit_shas": self.commit_shas,
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionOutcome:
    decision: StrategyDecision
    memory_summary: dict[str, Any]
    requires_human_approval: bool = False
    reasons: tuple[str, ...] = ()


def _result_by_id(
    results: Iterable[EvaluationResult], evaluator_id: str
) -> EvaluationResult | None:
    matches = [result for result in results if result.evaluator_id == evaluator_id]
    if not matches:
        return None
    return max(matches, key=lambda result: result.evaluator_version)


def _measured_value(result: EvaluationResult | None) -> float | None:
    if result is None or result.score.state != MeasurementState.MEASURED:
        return None
    if result.score.value is None:
        return None
    return float(result.score.value)


def _mandatory_failures(results: Iterable[EvaluationResult]) -> tuple[str, ...]:
    failures: list[str] = []
    for result in results:
        if result.evidence.get("mandatory_gate") and result.passed is not True:
            failures.append(result.evaluator_id)
    return tuple(sorted(set(failures)))


def _aggregate_metric(
    results: Iterable[EvaluationResult], field_name: str
) -> float | None:
    values: list[float] = []
    for result in results:
        metric = getattr(result, field_name)
        if metric.state == MeasurementState.MEASURED and metric.value is not None:
            values.append(float(metric.value))
    if not values:
        return None
    return sum(values) / len(values)


def _reduction_ratio(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline <= 0:
        return None
    return (baseline - candidate) / baseline


def decide_strategy(
    *,
    task_class: EvaluationTaskClass,
    baseline: StrategySpec,
    candidate: StrategySpec,
    evidence: PromotionEvidence,
    policy: PromotionPolicy,
    decision_id: str,
    scope: dict[str, Any] | None = None,
    owner_approved: bool = False,
    supersedes_decision_id: str | None = None,
) -> PromotionOutcome:
    if baseline.task_class_id != task_class.task_class_id:
        raise ValueError("baseline task class mismatch")
    if candidate.task_class_id != task_class.task_class_id:
        raise ValueError("candidate task class mismatch")

    candidate_gate_failures = _mandatory_failures(evidence.candidate_results)
    baseline_primary = _measured_value(
        _result_by_id(evidence.baseline_results, task_class.primary_metric)
    )
    candidate_primary = _measured_value(
        _result_by_id(evidence.candidate_results, task_class.primary_metric)
    )

    baseline_cost = _aggregate_metric(evidence.baseline_results, "cost_usd")
    candidate_cost = _aggregate_metric(evidence.candidate_results, "cost_usd")
    baseline_latency = _aggregate_metric(evidence.baseline_results, "latency_ms")
    candidate_latency = _aggregate_metric(evidence.candidate_results, "latency_ms")

    cost_reduction = _reduction_ratio(baseline_cost, candidate_cost)
    latency_reduction = _reduction_ratio(baseline_latency, candidate_latency)

    reasons: list[str] = []
    state = StrategyDecisionState.KEEP_BASELINE

    if candidate_gate_failures:
        state = StrategyDecisionState.REJECT_SAFETY
        reasons.append("mandatory_gate_failure:" + ",".join(candidate_gate_failures))
    elif candidate_primary is None or baseline_primary is None:
        state = StrategyDecisionState.UNMEASURED
        reasons.append("primary_metric_unmeasured")
    elif candidate_primary < policy.minimum_primary_score:
        state = StrategyDecisionState.REJECT_QUALITY
        reasons.append("candidate_below_quality_floor")
    else:
        primary_improvement = candidate_primary - baseline_primary
        equivalent_quality = (
            candidate_primary + policy.equivalent_quality_tolerance >= baseline_primary
        )
        materially_better = primary_improvement >= policy.minimum_absolute_improvement
        materially_cheaper = (
            cost_reduction is not None
            and cost_reduction >= policy.minimum_cost_reduction_ratio
            and equivalent_quality
        )
        materially_faster = (
            latency_reduction is not None
            and latency_reduction >= policy.minimum_latency_reduction_ratio
            and equivalent_quality
        )

        if materially_better or materially_cheaper or materially_faster:
            state = StrategyDecisionState.PROMOTE
            if materially_better:
                reasons.append("primary_metric_improved")
            if materially_cheaper:
                reasons.append("equivalent_quality_lower_cost")
            if materially_faster:
                reasons.append("equivalent_quality_lower_latency")
        else:
            reasons.append("no_material_benefit")

    requires_human_approval = task_class.risk_class.lower() in {
        value.lower() for value in policy.high_risk_classes
    }
    if (
        state == StrategyDecisionState.PROMOTE
        and requires_human_approval
        and not owner_approved
    ):
        state = StrategyDecisionState.LIMITED_CANARY
        reasons.append("owner_approval_required_for_full_promotion")

    rollback = (
        baseline.fingerprint
        if state
        in {StrategyDecisionState.PROMOTE, StrategyDecisionState.LIMITED_CANARY}
        else None
    )
    decision = StrategyDecision(
        decision_id=decision_id,
        task_class_id=task_class.task_class_id,
        baseline_strategy_fingerprint=baseline.fingerprint,
        candidate_strategy_fingerprint=candidate.fingerprint,
        state=state,
        evaluation_fingerprints=tuple(
            sorted(
                result.fingerprint
                for result in (*evidence.baseline_results, *evidence.candidate_results)
            )
        ),
        decision_policy_version=policy.version,
        rollback_strategy_fingerprint=rollback,
        scope=scope or {},
        provenance={
            "promotion_evidence_fingerprint": evidence.fingerprint,
            "evaluator_set_fingerprint": evidence.evaluator_set_fingerprint,
            "case_fingerprints": evidence.case_fingerprints,
            "issue_refs": evidence.issue_refs,
            "pr_refs": evidence.pr_refs,
            "commit_shas": evidence.commit_shas,
        },
        supersedes_decision_id=supersedes_decision_id,
    )

    memory_summary = {
        "task_class_id": task_class.task_class_id,
        "risk_class": task_class.risk_class,
        "baseline_strategy_fingerprint": baseline.fingerprint,
        "candidate_strategy_fingerprint": candidate.fingerprint,
        "evaluator_set_fingerprint": evidence.evaluator_set_fingerprint,
        "case_fingerprints": evidence.case_fingerprints,
        "primary_metric": task_class.primary_metric,
        "baseline_primary": baseline_primary,
        "candidate_primary": candidate_primary,
        "baseline_cost_usd": baseline_cost,
        "candidate_cost_usd": candidate_cost,
        "baseline_latency_ms": baseline_latency,
        "candidate_latency_ms": candidate_latency,
        "decision": state.value,
        "measured_outcome": (
            "benefit"
            if state
            in {StrategyDecisionState.PROMOTE, StrategyDecisionState.LIMITED_CANARY}
            else "unmeasured"
            if state == StrategyDecisionState.UNMEASURED
            else "no-benefit"
        ),
        "rollback_strategy_fingerprint": rollback,
        "requires_human_approval": requires_human_approval,
        "reasons": tuple(reasons),
        "issue_refs": evidence.issue_refs,
        "pr_refs": evidence.pr_refs,
        "commit_shas": evidence.commit_shas,
    }
    return PromotionOutcome(
        decision=decision,
        memory_summary=memory_summary,
        requires_human_approval=requires_human_approval,
        reasons=tuple(reasons),
    )
