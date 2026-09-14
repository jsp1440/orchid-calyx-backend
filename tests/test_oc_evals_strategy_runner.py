import pytest

from app.evals.evaluators import (
    FrozenEvaluationOutput,
    build_default_scientific_registry,
)
from app.evals.models import EvaluationCase, StrategySpec, stable_fingerprint
from app.evals.strategy_runner import (
    BoundedStrategyExperimentRunner,
    DuplicateExperimentDispatch,
    ExperimentBudget,
    ExperimentBudgetExceeded,
    StrategyExecutionArtifact,
)


def strategy(strategy_id: str, version: str = "1") -> StrategySpec:
    return StrategySpec(
        strategy_id=strategy_id,
        version=version,
        task_class_id="taxonomy-research",
        implementation_ref=f"fixture:{strategy_id}:{version}",
    )


def case(version: str = "1") -> EvaluationCase:
    return EvaluationCase(
        case_id="orchid-1",
        version=version,
        task_class_id="taxonomy-research",
        input_ref="fixture:input",
        expected_ref="fixture:expected",
    )


def payload() -> dict[str, object]:
    return {
        "citation_anchor_valid": True,
        "taxonomy_correct": True,
        "evidence_inference_separated": True,
        "counterevidence_preserved": True,
        "uncertainty_explicit": True,
        "unsupported_claims_absent": True,
        "contradictions_preserved": True,
        "abstention_valid": True,
        "protected_locality_safe": True,
        "rights_access_compliant": True,
        "structured_output_valid": True,
        "idempotent": True,
        "precision": 0.9,
        "recall": 0.8,
        "completeness": 0.85,
    }


def make_executor(
    *, cost: float | None = 0.0, latency: int | None = 10, attempts: int = 1
):
    calls: list[str] = []

    def execute(
        spec: StrategySpec, eval_case: EvaluationCase
    ) -> StrategyExecutionArtifact:
        calls.append(spec.strategy_id)
        return StrategyExecutionArtifact(
            strategy_fingerprint=spec.fingerprint,
            case_fingerprint=eval_case.fingerprint,
            output=FrozenEvaluationOutput(
                output_id=f"out:{spec.strategy_id}",
                task_class_id=spec.task_class_id,
                payload=payload(),
            ),
            cost_usd=cost,
            latency_ms=latency,
            attempts=attempts,
        )

    return execute, calls


def test_baseline_candidate_run_is_idempotent_without_duplicate_dispatch():
    executor, calls = make_executor()
    runner = BoundedStrategyExperimentRunner(
        build_default_scientific_registry(), executor
    )
    baseline = strategy("baseline")
    candidate = strategy("candidate")
    eval_case = case()

    first = runner.run(
        task_class_id="taxonomy-research",
        baseline=baseline,
        candidate=candidate,
        case=eval_case,
        budget=ExperimentBudget(),
    )
    second = runner.run(
        task_class_id="taxonomy-research",
        baseline=baseline,
        candidate=candidate,
        case=eval_case,
        budget=ExperimentBudget(),
    )

    assert first == second
    assert calls == ["baseline", "candidate"]
    assert first.baseline_result_fingerprints
    assert first.candidate_result_fingerprints


def test_requires_budget_for_both_baseline_and_candidate():
    executor, calls = make_executor()
    runner = BoundedStrategyExperimentRunner(
        build_default_scientific_registry(), executor
    )

    with pytest.raises(ExperimentBudgetExceeded, match="two executions"):
        runner.run(
            task_class_id="taxonomy-research",
            baseline=strategy("baseline"),
            candidate=strategy("candidate"),
            case=case(),
            budget=ExperimentBudget(max_executions=1),
        )

    assert calls == []


def test_cost_and_retry_budgets_fail_closed():
    executor, _ = make_executor(cost=0.6, attempts=2)
    runner = BoundedStrategyExperimentRunner(
        build_default_scientific_registry(), executor
    )

    with pytest.raises(ExperimentBudgetExceeded):
        runner.run(
            task_class_id="taxonomy-research",
            baseline=strategy("baseline"),
            candidate=strategy("candidate"),
            case=case(),
            budget=ExperimentBudget(max_cost_usd=1.0, max_retries_per_strategy=0),
        )


def test_suppressed_unchanged_candidate_is_not_dispatched():
    executor, calls = make_executor()
    registry = build_default_scientific_registry()
    runner = BoundedStrategyExperimentRunner(registry, executor)
    baseline = strategy("baseline")
    candidate = strategy("candidate")
    eval_case = case()
    material = stable_fingerprint(
        {
            "task_class_id": "taxonomy-research",
            "baseline": baseline.fingerprint,
            "candidate": candidate.fingerprint,
            "case": eval_case.fingerprint,
            "evaluators": registry.fingerprint,
        }
    )
    runner.suppress_candidate(material)

    with pytest.raises(DuplicateExperimentDispatch, match="suppressed"):
        runner.run(
            task_class_id="taxonomy-research",
            baseline=baseline,
            candidate=candidate,
            case=eval_case,
            budget=ExperimentBudget(),
        )

    assert calls == []


def test_stale_executor_artifact_is_rejected():
    def stale_executor(
        spec: StrategySpec, eval_case: EvaluationCase
    ) -> StrategyExecutionArtifact:
        return StrategyExecutionArtifact(
            strategy_fingerprint="stale",
            case_fingerprint=eval_case.fingerprint,
            output=FrozenEvaluationOutput(
                output_id="stale",
                task_class_id=spec.task_class_id,
                payload=payload(),
            ),
        )

    runner = BoundedStrategyExperimentRunner(
        build_default_scientific_registry(), stale_executor
    )
    with pytest.raises(ValueError, match="strategy fingerprint"):
        runner.run(
            task_class_id="taxonomy-research",
            baseline=strategy("baseline"),
            candidate=strategy("candidate"),
            case=case(),
            budget=ExperimentBudget(),
        )


def test_material_change_allows_retest_after_prior_suppression():
    executor, calls = make_executor()
    registry = build_default_scientific_registry()
    runner = BoundedStrategyExperimentRunner(registry, executor)
    baseline = strategy("baseline")
    old_candidate = strategy("candidate", "1")
    new_candidate = strategy("candidate", "2")
    eval_case = case()

    old_material = stable_fingerprint(
        {
            "task_class_id": "taxonomy-research",
            "baseline": baseline.fingerprint,
            "candidate": old_candidate.fingerprint,
            "case": eval_case.fingerprint,
            "evaluators": registry.fingerprint,
        }
    )
    runner.suppress_candidate(old_material)

    result = runner.run(
        task_class_id="taxonomy-research",
        baseline=baseline,
        candidate=new_candidate,
        case=eval_case,
        budget=ExperimentBudget(),
    )

    assert result.candidate.strategy_fingerprint == new_candidate.fingerprint
    assert calls == ["baseline", "candidate"]
