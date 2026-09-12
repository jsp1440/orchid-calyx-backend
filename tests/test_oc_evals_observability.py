from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.evals.models import (
    EvaluationResult,
    MetricValue,
    MeasurementState,
    StrategyDecision,
    StrategyDecisionState,
)
from app.evals.observability import (
    build_strategy_status,
    get_evaluation_repository,
    router,
)
from app.evals.repository import InMemoryEvaluationRepository
from app.security import verify_owner_or_api_key


def measured(value, unit=None):
    return MetricValue(MeasurementState.MEASURED, value=value, unit=unit)


def test_snapshot_preserves_unknown_and_unavailable_semantics_and_redacts_provenance():
    repo = InMemoryEvaluationRepository()
    result = EvaluationResult(
        run_identity_fingerprint="run-1",
        evaluator_id="citation-validity",
        evaluator_version="1",
        passed=True,
        score=measured(0.98),
        latency_ms=MetricValue(MeasurementState.UNKNOWN),
        cost_usd=MetricValue(MeasurementState.UNAVAILABLE),
        usage_units=measured(0),
    )
    repo.put_result(result)
    decision = StrategyDecision(
        decision_id="decision-1",
        task_class_id="literature-answer",
        baseline_strategy_fingerprint="baseline",
        candidate_strategy_fingerprint="candidate",
        state=StrategyDecisionState.PROMOTE,
        evaluation_fingerprints=(result.fingerprint,),
        decision_policy_version="1",
        rollback_strategy_fingerprint="baseline",
        scope={"risk_class": "bounded"},
        provenance={
            "issue": 1377,
            "pr": 1383,
            "sha": "abc123",
            "evaluated_at": "2026-09-12T11:00:00Z",
            "locality": "sensitive-place",
            "latitude": -1.23,
            "private_reasoning": "never expose",
        },
    )
    repo.put_decision(decision)

    payload = build_strategy_status(repo)
    row = payload["strategies"][0]
    metrics = row["evaluation_results"][0]

    assert row["active_strategy_fingerprint"] == "candidate"
    assert row["rollback_strategy_fingerprint"] == "baseline"
    assert metrics["latency_ms"] == {"state": "UNKNOWN", "value": None, "unit": None}
    assert metrics["cost_usd"] == {"state": "UNAVAILABLE", "value": None, "unit": None}
    assert metrics["usage_units"]["value"] == 0
    assert row["evidence"] == {
        "evaluated_at": "2026-09-12T11:00:00Z",
        "issue": 1377,
        "pr": 1383,
        "sha": "abc123",
    }


def test_missing_evaluation_result_is_unavailable_not_zero():
    repo = InMemoryEvaluationRepository()
    repo.put_decision(
        StrategyDecision(
            decision_id="decision-missing",
            task_class_id="taxonomy-check",
            baseline_strategy_fingerprint="baseline",
            candidate_strategy_fingerprint="candidate",
            state=StrategyDecisionState.UNMEASURED,
            evaluation_fingerprints=("missing-result",),
            decision_policy_version="1",
            rollback_strategy_fingerprint=None,
        )
    )

    row = build_strategy_status(repo)["strategies"][0]
    result = row["evaluation_results"][0]
    assert result["status"] == "UNAVAILABLE"
    assert result["score"]["value"] is None
    assert row["active_strategy_fingerprint"] == "baseline"


def test_rejected_strategy_keeps_baseline_and_reports_regression():
    repo = InMemoryEvaluationRepository()
    result = EvaluationResult(
        run_identity_fingerprint="run-bad",
        evaluator_id="protected-locality",
        evaluator_version="1",
        passed=False,
        score=measured(0.0),
    )
    repo.put_result(result)
    repo.put_decision(
        StrategyDecision(
            decision_id="decision-bad",
            task_class_id="atlas-answer",
            baseline_strategy_fingerprint="baseline",
            candidate_strategy_fingerprint="candidate",
            state=StrategyDecisionState.REJECT_SAFETY,
            evaluation_fingerprints=(result.fingerprint,),
            decision_policy_version="1",
            rollback_strategy_fingerprint=None,
        )
    )

    row = build_strategy_status(repo)["strategies"][0]
    assert row["active_strategy_fingerprint"] == "baseline"
    assert row["regression_detected"] is True
    assert row["failed_evaluators"] == ["protected-locality"]


def test_route_is_owner_protected_and_uses_canonical_dependency():
    repo = InMemoryEvaluationRepository()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner"}
    app.dependency_overrides[get_evaluation_repository] = lambda: repo

    response = TestClient(app).get("/api/mission-control/evals/strategies")
    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert response.json()["strategies"] == []
