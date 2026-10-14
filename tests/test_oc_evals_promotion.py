from app.evals.models import (
    EvaluationResult,
    EvaluationTaskClass,
    MeasurementState,
    MetricValue,
    StrategyDecisionState,
    StrategySpec,
)
from app.evals.promotion import PromotionEvidence, PromotionPolicy, decide_strategy


def metric(value: float, unit: str = "ratio") -> MetricValue:
    return MetricValue(MeasurementState.MEASURED, value, unit)


def result(
    evaluator_id: str,
    score: float,
    *,
    mandatory: bool = False,
    passed: bool | None = True,
    cost: float | None = None,
    latency: float | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        run_identity_fingerprint=f"run-{evaluator_id}-{score}",
        evaluator_id=evaluator_id,
        evaluator_version="1",
        passed=passed,
        score=metric(score),
        cost_usd=(metric(cost, "usd") if cost is not None else MetricValue(MeasurementState.UNKNOWN)),
        latency_ms=(metric(latency, "ms") if latency is not None else MetricValue(MeasurementState.UNKNOWN)),
        evidence={"mandatory_gate": mandatory},
    )


def strategies(risk_class: str = "standard"):
    task = EvaluationTaskClass(
        task_class_id="scientific.answer",
        version="1",
        risk_class=risk_class,
        primary_metric="precision",
        mandatory_gate_ids=("citation_anchor_valid",),
    )
    baseline = StrategySpec(
        strategy_id="baseline",
        version="1",
        task_class_id=task.task_class_id,
        implementation_ref="impl:baseline@1",
    )
    candidate = StrategySpec(
        strategy_id="candidate",
        version="1",
        task_class_id=task.task_class_id,
        implementation_ref="impl:candidate@1",
    )
    return task, baseline, candidate


def evidence(baseline_results, candidate_results):
    return PromotionEvidence(
        baseline_results=tuple(baseline_results),
        candidate_results=tuple(candidate_results),
        evaluator_set_fingerprint="evalset-v1",
        case_fingerprints=("case-a",),
        issue_refs=("#1377",),
        pr_refs=("PR:test",),
        commit_shas=("abc123",),
    )


def test_promotes_measurably_better_candidate_with_rollback_and_memory():
    task, baseline, candidate = strategies()
    outcome = decide_strategy(
        task_class=task,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence(
            [result("precision", 0.80), result("citation_anchor_valid", 1.0, mandatory=True)],
            [result("precision", 0.90), result("citation_anchor_valid", 1.0, mandatory=True)],
        ),
        policy=PromotionPolicy(minimum_primary_score=0.75, minimum_absolute_improvement=0.05),
        decision_id="decision-1",
        scope={"task_class": task.task_class_id},
    )
    assert outcome.decision.state == StrategyDecisionState.PROMOTE
    assert outcome.decision.rollback_strategy_fingerprint == baseline.fingerprint
    assert outcome.memory_summary["measured_outcome"] == "benefit"
    assert outcome.memory_summary["rollback_strategy_fingerprint"] == baseline.fingerprint


def test_equivalent_quality_lower_cost_can_promote():
    task, baseline, candidate = strategies()
    outcome = decide_strategy(
        task_class=task,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence(
            [result("precision", 0.90, cost=1.00), result("citation_anchor_valid", 1.0, mandatory=True)],
            [result("precision", 0.90, cost=0.40), result("citation_anchor_valid", 1.0, mandatory=True)],
        ),
        policy=PromotionPolicy(
            minimum_primary_score=0.80,
            minimum_absolute_improvement=0.05,
            equivalent_quality_tolerance=0.01,
            minimum_cost_reduction_ratio=0.30,
        ),
        decision_id="decision-2",
    )
    assert outcome.decision.state == StrategyDecisionState.PROMOTE
    assert "equivalent_quality_lower_cost" in outcome.reasons


def test_mandatory_gate_failure_rejects_even_if_candidate_is_better_and_cheaper():
    task, baseline, candidate = strategies()
    outcome = decide_strategy(
        task_class=task,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence(
            [result("precision", 0.80, cost=1.00), result("citation_anchor_valid", 1.0, mandatory=True)],
            [
                result("precision", 0.99, cost=0.01),
                result("citation_anchor_valid", 0.0, mandatory=True, passed=False),
            ],
        ),
        policy=PromotionPolicy(minimum_absolute_improvement=0.01),
        decision_id="decision-3",
    )
    assert outcome.decision.state == StrategyDecisionState.REJECT_SAFETY
    assert outcome.decision.rollback_strategy_fingerprint is None
    assert outcome.memory_summary["measured_outcome"] == "no-benefit"


def test_no_material_benefit_keeps_baseline_and_records_suppression_ready_outcome():
    task, baseline, candidate = strategies()
    outcome = decide_strategy(
        task_class=task,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence(
            [result("precision", 0.90), result("citation_anchor_valid", 1.0, mandatory=True)],
            [result("precision", 0.91), result("citation_anchor_valid", 1.0, mandatory=True)],
        ),
        policy=PromotionPolicy(minimum_absolute_improvement=0.05),
        decision_id="decision-4",
    )
    assert outcome.decision.state == StrategyDecisionState.KEEP_BASELINE
    assert outcome.memory_summary["measured_outcome"] == "no-benefit"
    assert "no_material_benefit" in outcome.reasons


def test_high_risk_improvement_requires_owner_approval_for_full_promotion():
    task, baseline, candidate = strategies(risk_class="high")
    common = dict(
        task_class=task,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence(
            [result("precision", 0.80), result("citation_anchor_valid", 1.0, mandatory=True)],
            [result("precision", 0.95), result("citation_anchor_valid", 1.0, mandatory=True)],
        ),
        policy=PromotionPolicy(minimum_absolute_improvement=0.05),
        scope={"taxon": "fixture-only"},
    )
    canary = decide_strategy(**common, decision_id="decision-5")
    assert canary.decision.state == StrategyDecisionState.LIMITED_CANARY
    assert canary.requires_human_approval is True
    assert canary.decision.rollback_strategy_fingerprint == baseline.fingerprint

    approved = decide_strategy(**common, decision_id="decision-6", owner_approved=True)
    assert approved.decision.state == StrategyDecisionState.PROMOTE


def test_missing_primary_metric_is_unmeasured_not_zero():
    task, baseline, candidate = strategies()
    outcome = decide_strategy(
        task_class=task,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence(
            [result("citation_anchor_valid", 1.0, mandatory=True)],
            [result("citation_anchor_valid", 1.0, mandatory=True)],
        ),
        policy=PromotionPolicy(),
        decision_id="decision-7",
    )
    assert outcome.decision.state == StrategyDecisionState.UNMEASURED
    assert outcome.memory_summary["baseline_primary"] is None
    assert outcome.memory_summary["candidate_primary"] is None
    assert outcome.memory_summary["measured_outcome"] == "unmeasured"
