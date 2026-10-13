"""The OC evaluators run unchanged inside DeepEval when it is installed.

Skipped when deepeval is absent: it is an optional harness, never a runtime
dependency. The dedicated CI job installs a pinned deepeval with telemetry off
and no provider credentials, so any attempted model call would fail the job.
"""

from __future__ import annotations

import copy
import os

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
pytest.importorskip("deepeval")

from runtime.evals import evaluators as ev
from runtime.evals.deepeval_adapter import (
    to_deepeval_metric,
    to_test_case,
)
from runtime.evals.fixtures import load_cases, load_outputs
from tests.test_oc_evals import FIXTURES

CASES = {c.case_id: c for c in load_cases(FIXTURES)}


@pytest.mark.parametrize(
    "evaluator", ev.DETERMINISTIC_EVALUATORS, ids=lambda e: e.metric_id
)
def test_deepeval_metric_matches_native_result(evaluator) -> None:
    case = CASES["c2-lexicon-schema"]
    for name in ("baseline", "candidate_better"):
        output = load_outputs(FIXTURES, name)[case.case_id]
        native = evaluator.evaluate(case, output)
        metric = to_deepeval_metric(evaluator)
        score = metric.measure(to_test_case(case, output))
        assert score == float(native.score)
        assert metric.is_successful() is (
            bool(native.passed) and score >= metric.threshold
        )


def test_unmeasured_maps_to_no_score_and_failure() -> None:
    case = CASES["c1-null-guard"]
    output = copy.deepcopy(load_outputs(FIXTURES, "baseline")[case.case_id])
    output.pop("checks")
    metric = to_deepeval_metric(ev.TEST_OUTCOMES)
    assert metric.measure(to_test_case(case, output)) is None
    assert metric.is_successful() is False
    assert "UNMEASURED" in metric.error


def test_gate_metric_needs_a_full_pass() -> None:
    metric = to_deepeval_metric(ev.SCOPE_COMPLIANCE)
    assert metric.threshold == 1.0


def test_provider_evaluators_are_not_adapted() -> None:
    with pytest.raises(ValueError):
        to_deepeval_metric(ev.RUBRIC_JUDGE)


def test_assert_test_runs_offline() -> None:
    from deepeval import assert_test

    case = CASES["c1-null-guard"]
    output = load_outputs(FIXTURES, "candidate_better")[case.case_id]
    assert_test(
        to_test_case(case, output),
        [to_deepeval_metric(e) for e in ev.DETERMINISTIC_EVALUATORS],
        run_async=False,
    )
