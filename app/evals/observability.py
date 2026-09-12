from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.security import verify_owner_or_api_key

from .models import MeasurementState, MetricValue, StrategyDecisionState
from .repository import InMemoryEvaluationRepository

_RUNTIME_REPOSITORY = InMemoryEvaluationRepository()


def get_evaluation_repository() -> InMemoryEvaluationRepository:
    """Return the canonical in-process evaluation repository dependency.

    Production persistence may replace this dependency without changing the
    read-only Mission Control contract.
    """

    return _RUNTIME_REPOSITORY


def _metric_payload(metric: MetricValue) -> dict[str, Any]:
    return {
        "state": metric.state.value,
        "value": metric.value if metric.state == MeasurementState.MEASURED else None,
        "unit": metric.unit,
    }


def _evidence_payload(provenance: dict[str, Any]) -> dict[str, Any]:
    """Expose evidence locators only; never arbitrary provenance/config payloads."""

    allowed = {
        "issue",
        "issue_url",
        "pr",
        "pr_url",
        "sha",
        "commit_sha",
        "workflow_run",
        "workflow_url",
        "evaluation_run",
        "evaluation_artifact",
        "evaluated_at",
    }
    return {key: provenance[key] for key in sorted(allowed & provenance.keys())}


def _decision_active_strategy(decision) -> str:
    if decision.state in {StrategyDecisionState.PROMOTE, StrategyDecisionState.LIMITED_CANARY}:
        return decision.candidate_strategy_fingerprint
    return decision.baseline_strategy_fingerprint


def build_strategy_status(repo: InMemoryEvaluationRepository) -> dict[str, Any]:
    """Build a truthful read-only snapshot from canonical evaluation records."""

    latest_by_task: dict[str, Any] = {}
    for decision in repo.decisions.values():
        latest_by_task[decision.task_class_id] = decision

    rows: list[dict[str, Any]] = []
    for task_class_id, decision in sorted(latest_by_task.items()):
        result_rows = []
        failures: list[str] = []
        for fingerprint in decision.evaluation_fingerprints:
            result = repo.results.get(fingerprint)
            if result is None:
                result_rows.append(
                    {
                        "evaluation_fingerprint": fingerprint,
                        "status": "UNAVAILABLE",
                        "score": {"state": "UNAVAILABLE", "value": None, "unit": None},
                        "latency_ms": {"state": "UNAVAILABLE", "value": None, "unit": None},
                        "cost_usd": {"state": "UNAVAILABLE", "value": None, "unit": None},
                        "usage_units": {"state": "UNAVAILABLE", "value": None, "unit": None},
                    }
                )
                continue
            if result.passed is False:
                failures.append(result.evaluator_id)
            result_rows.append(
                {
                    "evaluation_fingerprint": fingerprint,
                    "evaluator_id": result.evaluator_id,
                    "evaluator_version": result.evaluator_version,
                    "passed": result.passed,
                    "score": _metric_payload(result.score),
                    "latency_ms": _metric_payload(result.latency_ms),
                    "cost_usd": _metric_payload(result.cost_usd),
                    "usage_units": _metric_payload(result.usage_units),
                }
            )

        rows.append(
            {
                "task_class_id": task_class_id,
                "decision_id": decision.decision_id,
                "decision_state": decision.state.value,
                "active_strategy_fingerprint": _decision_active_strategy(decision),
                "baseline_strategy_fingerprint": decision.baseline_strategy_fingerprint,
                "candidate_strategy_fingerprint": decision.candidate_strategy_fingerprint,
                "rollback_strategy_fingerprint": decision.rollback_strategy_fingerprint,
                "decision_policy_version": decision.decision_policy_version,
                "scope": dict(decision.scope),
                "last_evaluated_at": decision.provenance.get("evaluated_at"),
                "evaluation_results": result_rows,
                "failed_evaluators": sorted(failures),
                "regression_detected": bool(failures)
                or decision.state
                in {
                    StrategyDecisionState.REJECT_QUALITY,
                    StrategyDecisionState.REJECT_SAFETY,
                    StrategyDecisionState.REJECT_INSTABILITY,
                },
                "evidence": _evidence_payload(decision.provenance),
            }
        )

    return {
        "schema_version": "oc.evals.mission-control.v1",
        "read_only": True,
        "strategies": rows,
        "counts": {
            "task_classes": len(rows),
            "promoted": sum(row["decision_state"] == "PROMOTE" for row in rows),
            "limited_canary": sum(row["decision_state"] == "LIMITED_CANARY" for row in rows),
            "rejected_or_no_benefit": sum(
                row["decision_state"]
                in {
                    "KEEP_BASELINE",
                    "REJECT_QUALITY",
                    "REJECT_SAFETY",
                    "REJECT_COST",
                    "REJECT_INSTABILITY",
                }
                for row in rows
            ),
            "unmeasured": sum(row["decision_state"] == "UNMEASURED" for row in rows),
        },
    }


router = APIRouter(
    prefix="/api/mission-control/evals",
    tags=["mission-control", "evals"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


@router.get("/strategies")
def strategy_status(
    repo: InMemoryEvaluationRepository = Depends(get_evaluation_repository),  # noqa: B008
) -> dict[str, Any]:
    return build_strategy_status(repo)
