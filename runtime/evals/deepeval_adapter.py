"""Optional DeepEval compatibility for OC-EVALS-001 evaluators.

DeepEval is not a runtime dependency. This adapter lets the deterministic
evaluators run inside a DeepEval/pytest harness (``deepeval test run``) when the
library is installed, without changing their semantics:

* each OC evaluator becomes a ``deepeval.metrics.BaseMetric`` whose ``measure``
  runs the same deterministic function -- no LLM, no network;
* the OC case and output travel in ``LLMTestCase.metadata``;
* an UNMEASURED OC result maps to ``score=None`` and ``success=False`` with the
  reason preserved, never to a zero score;
* a gate evaluator's threshold is 1.0: anything short of a full pass fails.

Set ``DEEPEVAL_TELEMETRY_OPT_OUT=YES`` when running offline; this module never
configures a judge model and never makes a provider call.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from runtime.evals.contracts import EvaluationCase, MeasurementState
from runtime.evals.evaluators import Evaluator


def _deepeval():
    try:
        from deepeval.metrics import BaseMetric
        from deepeval.test_case import LLMTestCase
    except ImportError as exc:  # pragma: no cover - exercised only without deepeval
        raise RuntimeError(
            "deepeval is not installed; the OC evaluators run without it"
        ) from exc
    return BaseMetric, LLMTestCase


def to_test_case(case: EvaluationCase, output: dict[str, Any]):
    _, LLMTestCase = _deepeval()
    return LLMTestCase(
        input=json.dumps(case.inputs, sort_keys=True),
        actual_output=json.dumps(
            {k: output.get(k) for k in ("head_sha", "changed_paths", "checks")},
            sort_keys=True,
        ),
        name=case.case_id,
        metadata={"oc_case": case, "oc_output": output},
    )


def to_deepeval_metric(evaluator: Evaluator, threshold: float | None = None):
    if evaluator.requires_provider:
        raise ValueError(
            f"{evaluator.metric_id} requires a provider; only offline evaluators are adapted"
        )
    BaseMetric, _ = _deepeval()

    class OCDeterministicMetric(BaseMetric):
        _required_params: ClassVar[list] = []

        def __init__(self) -> None:
            self.threshold = (
                threshold if threshold is not None else (1.0 if evaluator.gate else 0.5)
            )
            self.async_mode = False
            self.include_reason = True
            self.evaluation_model = None
            self.evaluation_cost = 0.0
            self.oc_result = None

        def measure(self, test_case, *args, **kwargs) -> float | None:
            metadata = test_case.metadata or {}
            result = evaluator.evaluate(metadata["oc_case"], metadata["oc_output"])
            self.oc_result = result
            self.reason = "; ".join(result.reasons) or "ok"
            if result.state is MeasurementState.MEASURED:
                self.score = float(result.score)
                self.error = None
            else:
                self.score = None
                self.error = f"{result.state.value}: {self.reason}"
            self.success = self.is_successful()
            return self.score

        async def a_measure(self, test_case, *args, **kwargs) -> float | None:
            return self.measure(test_case)

        def is_successful(self) -> bool:
            if (
                self.oc_result is None
                or self.oc_result.state is not MeasurementState.MEASURED
            ):
                return False
            return bool(self.oc_result.passed) and self.score >= self.threshold

        @property
        def __name__(self) -> str:
            return f"OC {evaluator.metric_id} v{evaluator.version}"

    return OCDeterministicMetric()
