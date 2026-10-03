import pytest

from app.evals import (
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationTaskClass,
    InMemoryEvaluationRepository,
    MeasurementState,
    MetricValue,
    StrategyDecision,
    StrategyDecisionState,
    StrategySpec,
)


def _fixture():
    task = EvaluationTaskClass(
        task_class_id="literature.answer",
        version="1",
        risk_class="scientific-review",
        primary_metric="grounded_accuracy",
        mandatory_gate_ids=("citations", "protected-locality"),
    )
    baseline = StrategySpec(
        strategy_id="baseline",
        version="1",
        task_class_id=task.task_class_id,
        implementation_ref="sha:baseline",
        config={"retrieval": "deterministic"},
        evaluator_versions={"citations": "1"},
    )
    candidate = StrategySpec(
        strategy_id="candidate",
        version="1",
        task_class_id=task.task_class_id,
        implementation_ref="sha:candidate",
        config={"retrieval": "hybrid"},
        evaluator_versions={"citations": "1"},
    )
    case = EvaluationCase(
        case_id="case-1",
        version="1",
        task_class_id=task.task_class_id,
        input_ref="fixture://question/1",
        expected_ref="fixture://gold/1",
        provenance={"source": "reviewed-fixture"},
    )
    run = EvaluationRun(
        run_id="run-1",
        task_class_id=task.task_class_id,
        case_fingerprint=case.fingerprint,
        strategy_fingerprint=candidate.fingerprint,
        evaluator_set_fingerprint="evalset-v1",
        provenance={"issue": 1374},
    )
    result = EvaluationResult(
        run_identity_fingerprint=run.identity_fingerprint,
        evaluator_id="citations",
        evaluator_version="1",
        passed=True,
        score=MetricValue(MeasurementState.MEASURED, 0.98, "ratio"),
        latency_ms=MetricValue(MeasurementState.UNAVAILABLE),
        cost_usd=MetricValue(MeasurementState.UNKNOWN),
    )
    decision = StrategyDecision(
        decision_id="decision-1",
        task_class_id=task.task_class_id,
        baseline_strategy_fingerprint=baseline.fingerprint,
        candidate_strategy_fingerprint=candidate.fingerprint,
        state=StrategyDecisionState.PROMOTE,
        evaluation_fingerprints=(result.fingerprint,),
        decision_policy_version="1",
        rollback_strategy_fingerprint=baseline.fingerprint,
        provenance={"issue": 1374},
    )
    return task, baseline, candidate, case, run, result, decision


def test_fingerprints_are_stable_and_version_sensitive():
    task, baseline, *_ = _fixture()
    assert task.fingerprint == task.fingerprint
    changed = StrategySpec(
        strategy_id=baseline.strategy_id,
        version="2",
        task_class_id=baseline.task_class_id,
        implementation_ref=baseline.implementation_ref,
        config=baseline.config,
        evaluator_versions=baseline.evaluator_versions,
    )
    assert changed.fingerprint != baseline.fingerprint


def test_unknown_and_unavailable_are_not_zero():
    assert MetricValue(MeasurementState.UNKNOWN).value is None
    assert MetricValue(MeasurementState.UNAVAILABLE).value is None
    with pytest.raises(ValueError):
        MetricValue(MeasurementState.UNKNOWN, 0)
    with pytest.raises(ValueError):
        MetricValue(MeasurementState.MEASURED)


def test_promote_requires_rollback_identity():
    task, baseline, candidate, *_ = _fixture()
    with pytest.raises(ValueError):
        StrategyDecision(
            decision_id="bad",
            task_class_id=task.task_class_id,
            baseline_strategy_fingerprint=baseline.fingerprint,
            candidate_strategy_fingerprint=candidate.fingerprint,
            state=StrategyDecisionState.PROMOTE,
            evaluation_fingerprints=(),
            decision_policy_version="1",
            rollback_strategy_fingerprint=None,
        )


def test_repository_replay_is_idempotent():
    repo = InMemoryEvaluationRepository()
    task, baseline, candidate, case, run, result, decision = _fixture()
    for _ in range(2):
        repo.put_task_class(task)
        repo.put_strategy(baseline)
        repo.put_strategy(candidate)
        repo.put_case(case)
        repo.put_run(run)
        repo.put_result(result)
        repo.put_decision(decision)
    assert len(repo.task_classes) == 1
    assert len(repo.strategies) == 2
    assert len(repo.cases) == 1
    assert len(repo.runs) == 1
    assert len(repo.results) == 1
    assert len(repo.decisions) == 1


def test_decision_id_collision_fails_closed():
    repo = InMemoryEvaluationRepository()
    *_, decision = _fixture()
    repo.put_decision(decision)
    conflicting = StrategyDecision(
        decision_id=decision.decision_id,
        task_class_id=decision.task_class_id,
        baseline_strategy_fingerprint=decision.baseline_strategy_fingerprint,
        candidate_strategy_fingerprint=decision.candidate_strategy_fingerprint,
        state=StrategyDecisionState.KEEP_BASELINE,
        evaluation_fingerprints=decision.evaluation_fingerprints,
        decision_policy_version="1",
        rollback_strategy_fingerprint=None,
    )
    with pytest.raises(ValueError):
        repo.put_decision(conflicting)
