"""Evaluation runner (EVALS-001B): fixture-backed, reproducible, offline.

A run applies an evaluator suite to one strategy's outputs on a frozen case
set. The run id is a fingerprint of everything that determines the result
(strategy, cases, evaluator versions, outputs), so replaying the same inputs
yields the same run id and the same results: replay is idempotent.

NO_API_MODE uses the repository's fail-closed rule (scripts/oc_no_api_guard.py):
absent or any value other than an explicit disable means providers are blocked.
A provider-requiring evaluator is then PARKED, never executed and never scored.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from runtime.evals.contracts import (
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationTaskClass,
    MeasurementState,
    MetricSummary,
    StrategySpec,
    fingerprint,
)
from runtime.evals.evaluators import DETERMINISTIC_EVALUATORS, Evaluator

NO_API_GUARD = Path(__file__).resolve().parents[2] / "scripts" / "oc_no_api_guard.py"


def no_api_blocked(raw: str | None) -> bool:
    spec = importlib.util.spec_from_file_location("oc_no_api_guard", NO_API_GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("oc_no_api_guard", module)
    spec.loader.exec_module(module)
    return bool(module.evaluate(raw))


def _cost(outputs: Mapping[str, Mapping[str, Any]]) -> tuple[Decimal | None, str]:
    """Sum list-price estimates; any unknown case cost makes the total unknown."""
    total = Decimal(0)
    for output in outputs.values():
        cost = (output.get("receipt") or {}).get("cost") or {}
        if (
            cost.get("basis") != "list_price_estimate"
            or cost.get("estimated_usd") is None
        ):
            return None, "unavailable"
        total += Decimal(str(cost["estimated_usd"]))
    return (total, "list_price_estimate") if outputs else (None, "unavailable")


def _latency(outputs: Mapping[str, Mapping[str, Any]]) -> Decimal | None:
    values = [output.get("latency_seconds") for output in outputs.values()]
    if not values or any(v is None for v in values):
        return None
    return sum((Decimal(str(v)) for v in values), Decimal(0))


def _summaries(
    results: Sequence[EvaluationResult], metric_ids: Sequence[str]
) -> tuple[MetricSummary, ...]:
    summaries = []
    for metric_id in metric_ids:
        rows = [r for r in results if r.metric_id == metric_id]
        measured = [
            r.score
            for r in rows
            if r.state is MeasurementState.MEASURED and r.score is not None
        ]
        mean = (
            (sum(measured, Decimal(0)) / Decimal(len(measured))).quantize(
                Decimal("0.0001")
            )
            if measured
            else None
        )
        summaries.append(
            MetricSummary(metric_id, len(measured), len(rows) - len(measured), mean)
        )
    return tuple(summaries)


def run_evaluation(
    *,
    task_class: EvaluationTaskClass,
    strategy: StrategySpec,
    cases: Sequence[EvaluationCase],
    outputs: Mapping[str, Mapping[str, Any]],
    evaluators: Sequence[Evaluator] = DETERMINISTIC_EVALUATORS,
    code_sha: str | None = None,
    no_api_mode_raw: str | None = None,
) -> EvaluationRun:
    if strategy.task_class != task_class.identity:
        raise ValueError(
            f"strategy {strategy.identity} is for {strategy.task_class}, not {task_class.identity}"
        )
    for case in cases:
        if case.task_class != task_class.identity:
            raise ValueError(f"case {case.case_id} belongs to {case.task_class}")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("case ids must be unique")
    blocked = no_api_blocked(
        no_api_mode_raw
        if no_api_mode_raw is not None
        else os.environ.get("NO_API_MODE")
    )

    results: list[EvaluationResult] = []
    for case in sorted(cases, key=lambda c: c.case_id):
        output = outputs.get(case.case_id)
        for evaluator in evaluators:
            if evaluator.requires_provider and blocked:
                results.append(
                    EvaluationResult(
                        case.case_id, evaluator.metric_id, evaluator.version, MeasurementState.PARKED,
                        None, None, evaluator.gate, ("parked: NO_API_MODE blocks provider evaluators",),
                    )
                )  # fmt: skip
            elif output is None:
                results.append(
                    EvaluationResult(
                        case.case_id, evaluator.metric_id, evaluator.version, MeasurementState.UNMEASURED,
                        None, None, evaluator.gate, ("strategy produced no output for this case",),
                    )
                )  # fmt: skip
            else:
                results.append(evaluator.evaluate(case, output))

    case_outputs = {
        case.case_id: outputs[case.case_id] for case in cases if case.case_id in outputs
    }
    estimated_cost, cost_basis = (
        _cost(case_outputs)
        if len(case_outputs) == len(cases)
        else (None, "unavailable")
    )
    evaluator_versions = tuple((e.metric_id, e.version) for e in evaluators)
    case_set_fp = fingerprint(sorted(case.fingerprint for case in cases))
    outputs_fp = fingerprint(case_outputs)
    run_id = fingerprint(
        {
            "strategy": strategy.provenance_fingerprint,
            "cases": case_set_fp,
            "evaluators": evaluator_versions,
            "outputs": outputs_fp,
            "no_api": blocked,
        }
    )
    return EvaluationRun(
        run_id=run_id,
        task_class=task_class.identity,
        strategy=strategy.identity,
        strategy_fingerprint=strategy.provenance_fingerprint,
        case_set_fingerprint=case_set_fp,
        evaluator_versions=evaluator_versions,
        code_sha=code_sha,
        results=tuple(results),
        summaries=_summaries(results, [e.metric_id for e in evaluators]),
        estimated_cost_usd=estimated_cost,
        cost_basis=cost_basis,
        latency_seconds=_latency(case_outputs)
        if len(case_outputs) == len(cases)
        else None,
        no_api_mode=blocked,
        outputs_fingerprint=outputs_fp,
    )
