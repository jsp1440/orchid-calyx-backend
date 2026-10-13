"""OC-EVALS-001 deterministic evaluation layer.

The fixture set tests/fixtures/evals/coding_repair_v1 freezes one task class,
four cases and four strategies. Test names reference the blueprint's
acceptance items (A1..A12) where they prove one.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from runtime.evals import evaluators as ev
from runtime.evals.contracts import (
    DecisionKind,
    EvaluationCase,
    EvaluationResult,
    EvaluationTaskClass,
    MeasurementState,
    StrategyDecision,
)
from runtime.evals.decision import (
    PromotionPolicy,
    SuppressionLedger,
    decide,
    memory_summary,
    resolve_active_strategy,
)
from runtime.evals.fixtures import (
    load_cases,
    load_outputs,
    load_strategies,
    load_task_class,
)
from runtime.evals.runner import run_evaluation

REPO_ROOT = Path(__file__).parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "evals" / "coding_repair_v1"
TASK = load_task_class(FIXTURES)
CASES = load_cases(FIXTURES)
STRATEGIES = load_strategies(FIXTURES)
CASE = {c.case_id: c for c in CASES}


def _run(
    name: str, outputs=None, no_api="true", evaluators=ev.DETERMINISTIC_EVALUATORS
):
    return run_evaluation(
        task_class=TASK,
        strategy=STRATEGIES[name],
        cases=CASES,
        outputs=outputs if outputs is not None else load_outputs(FIXTURES, name),
        evaluators=evaluators,
        no_api_mode_raw=no_api,
    )


def _output(name: str, case_id: str) -> dict:
    return copy.deepcopy(load_outputs(FIXTURES, name)[case_id])


# --- contracts ---------------------------------------------------------------


def test_a1_task_class_is_versioned_and_validated() -> None:
    assert TASK.identity == "coding_repair_output_validation@1"
    with pytest.raises(ValueError):
        EvaluationTaskClass("x", "1", "extreme", "m", Decimal("0.5"))
    with pytest.raises(ValueError):
        EvaluationTaskClass("x", "1", "low", "m", Decimal("1.5"))


def test_a2_strategy_specs_are_frozen_and_fingerprinted() -> None:
    base, cand = STRATEGIES["baseline"], STRATEGIES["candidate_better"]
    assert base.provenance_fingerprint != cand.provenance_fingerprint
    with pytest.raises(AttributeError):
        base.version = "2"  # type: ignore[misc]


def test_unmeasured_result_cannot_carry_a_score() -> None:
    with pytest.raises(ValueError):
        EvaluationResult(
            "c", "m", "1", MeasurementState.UNMEASURED, Decimal(0), None, False
        )


def test_decision_cannot_authorize_anything() -> None:
    with pytest.raises(ValueError):
        StrategyDecision(
            DecisionKind.PROMOTE,
            "t",
            "b",
            "c",
            (),
            {},
            (),
            "s",
            "b",
            "r",
            authorizes=("merge",),
        )


# --- evaluators --------------------------------------------------------------


def test_test_outcomes_counts_only_passing_checks_on_the_output_head() -> None:
    out = _output("baseline", "c2-lexicon-schema")
    result = ev.TEST_OUTCOMES.evaluate(CASE["c2-lexicon-schema"], out)
    assert result.score == Decimal("0.5") and result.passed is False

    out = _output("candidate_better", "c1-null-guard")
    out["checks"][0]["head_sha"] = "0" * 40  # a pass about another commit
    result = ev.TEST_OUTCOMES.evaluate(CASE["c1-null-guard"], out)
    assert result.passed is False
    assert any("not the output head" in r for r in result.reasons)


def test_missing_facts_are_unmeasured_not_zero() -> None:
    empty: dict = {}
    for evaluator in ev.DETERMINISTIC_EVALUATORS:
        result = evaluator.evaluate(CASE["c1-null-guard"], empty)
        if evaluator is ev.PROVENANCE_COMPLETENESS:
            assert result.state is MeasurementState.MEASURED and result.score == 0
            continue
        assert result.state is MeasurementState.UNMEASURED, evaluator.metric_id
        assert result.score is None and result.passed is None


@pytest.mark.parametrize(
    "path,fragment",
    [
        (".github/workflows/ci.yml", "protected"),
        ("AGENTS.md", "protected"),
        (".claude/settings.json", "protected"),
        ("runtime/swarm/governor.py", "protected"),
        ("scripts/oc_no_api_guard.py", "protected"),
        ("config/.env", "protected"),
        ("../outside.py", "outside the repository"),
        ("/etc/passwd", "outside the repository"),
        ("app/other_module/x.py", "outside case scope"),
    ],
)
def test_scope_gate_rejects_protected_and_out_of_scope_paths(path, fragment) -> None:
    out = _output("candidate_better", "c1-null-guard")
    out["changed_paths"] = ["app/atlas/projection.py", path]
    result = ev.SCOPE_COMPLIANCE.evaluate(CASE["c1-null-guard"], out)
    assert result.gate_failed
    assert any(fragment in r for r in result.reasons)


def test_scope_protection_covers_the_executor_protected_set() -> None:
    spec = importlib.util.spec_from_file_location(
        "direct_for_scope", REPO_ROOT / "scripts" / "swarm_anthropic_direct.py"
    )
    direct = importlib.util.module_from_spec(spec)
    sys.modules["direct_for_scope"] = direct
    spec.loader.exec_module(direct)
    for path in direct.PROTECTED_FILES:
        assert ev._matches(path, ev.PROTECTED_PATTERNS), path
    for prefix in direct.PROTECTED_PREFIXES:
        assert ev._matches(prefix + "x", ev.PROTECTED_PATTERNS), prefix


def test_provenance_requires_full_head_sha() -> None:
    out = _output("candidate_better", "c1-null-guard")
    assert (
        ev.PROVENANCE_COMPLETENESS.evaluate(CASE["c1-null-guard"], out).passed is True
    )
    out["head_sha"] = out["head_sha"][:7]
    result = ev.PROVENANCE_COMPLETENESS.evaluate(CASE["c1-null-guard"], out)
    assert result.passed is False and "missing or invalid: head_sha" in result.reasons


def test_receipt_validity_recomputes_cost() -> None:
    out = _output("candidate_better", "c1-null-guard")
    assert ev.RECEIPT_VALIDITY.evaluate(CASE["c1-null-guard"], out).passed is True
    out["receipt"]["cost"]["estimated_usd"] = "0.000001"
    result = ev.RECEIPT_VALIDITY.evaluate(CASE["c1-null-guard"], out)
    assert result.gate_failed
    assert any("does not recompute" in r for r in result.reasons)


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda r: r.update(is_error=True), "disagrees"),
        (lambda r: r.pop("cost"), "missing cost"),
        (lambda r: r.update(num_turns=-1), "num_turns"),
        (lambda r: r["requestUsage"].pop(), "request usages"),
        (lambda r: r["cost"].update(billed_usd="1.00"), "billed amount"),
        (
            lambda r: next(iter(r["modelUsage"].values())).update(inputTokens=-5),
            "negative",
        ),
    ],
)
def test_receipt_validity_gate(mutate, fragment) -> None:
    out = _output("candidate_better", "c1-null-guard")
    mutate(out["receipt"])
    result = ev.RECEIPT_VALIDITY.evaluate(CASE["c1-null-guard"], out)
    assert result.gate_failed
    assert any(fragment in r for r in result.reasons), result.reasons


def test_receipt_priced_with_older_table_is_noted_not_failed() -> None:
    out = _output("candidate_better", "c1-null-guard")
    out["receipt"]["cost"]["pricing_version"] = "2020-01-01.1"
    out["receipt"]["cost"]["estimated_usd"] = "9.99"
    result = ev.RECEIPT_VALIDITY.evaluate(CASE["c1-null-guard"], out)
    assert result.passed is True
    assert any("not re-verified" in r for r in result.reasons)


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda e, h: e[0].update(head_sha=h[:7]), "abbreviated"),
        (lambda e, h: e[0].update(head_sha="1" * 40), "stale evidence"),
        (lambda e, h: e[0].pop("ref"), "no reference"),
        (lambda e, h: e[0].update(kind="review"), "no valid check_run"),
    ],
)
def test_evidence_must_name_the_exact_head(mutate, fragment) -> None:
    out = _output("candidate_better", "c4-locality-redaction")
    mutate(out["evidence"], out["head_sha"])
    for item in out["evidence"][1:]:
        item["kind"] = "test_log"
    result = ev.EVIDENCE_QUALITY.evaluate(CASE["c4-locality-redaction"], out)
    assert result.passed is False
    assert any(fragment in r for r in result.reasons), result.reasons


# --- runner ------------------------------------------------------------------


def test_a3_a4_a5_runs_share_frozen_cases_and_keep_unknowns_unknown() -> None:
    base, cand = _run("baseline"), _run("candidate_better")
    assert base.case_set_fingerprint == cand.case_set_fingerprint
    assert base.evaluator_versions == cand.evaluator_versions
    assert (
        base.estimated_cost_usd is not None and base.cost_basis == "list_price_estimate"
    )
    assert base.summary("test_outcomes").mean_score == Decimal("0.6250")
    assert cand.summary("test_outcomes").mean_score == Decimal("1.0000")

    outputs = load_outputs(FIXTURES, "candidate_better")
    outputs["c1-null-guard"]["receipt"]["cost"]["estimated_usd"] = None
    del outputs["c2-lexicon-schema"]["latency_seconds"]
    partial = _run("candidate_better", outputs)
    assert partial.estimated_cost_usd is None and partial.cost_basis == "unavailable"
    assert partial.latency_seconds is None


def test_missing_case_output_is_unmeasured() -> None:
    outputs = load_outputs(FIXTURES, "candidate_better")
    del outputs["c4-locality-redaction"]
    run = _run("candidate_better", outputs)
    rows = [r for r in run.results if r.case_id == "c4-locality-redaction"]
    assert rows and all(r.state is MeasurementState.UNMEASURED for r in rows)
    assert run.estimated_cost_usd is None


def test_a11_replay_is_idempotent() -> None:
    first, second = _run("candidate_better"), _run("candidate_better")
    assert first == second
    assert first.run_id == second.run_id


@pytest.mark.parametrize("raw", [None, "true", "1", "yes", "anything"])
def test_no_api_mode_parks_provider_evaluators_fail_closed(raw) -> None:
    run = _run(
        "baseline",
        no_api=raw if raw is not None else "",
        evaluators=(*ev.DETERMINISTIC_EVALUATORS, ev.RUBRIC_JUDGE),
    )
    if raw is None:
        # empty string is not an explicit disable: still blocked
        assert run.no_api_mode is True
    judge = [r for r in run.results if r.metric_id == "rubric_judge"]
    assert judge and all(
        r.state is MeasurementState.PARKED and r.score is None for r in judge
    )
    assert run.summary("rubric_judge").mean_score is None
    # Deterministic evaluators are unaffected by NO_API_MODE.
    assert run.summary("test_outcomes").mean_score == Decimal("0.6250")


def test_no_api_mode_absent_from_environment_is_blocked(monkeypatch) -> None:
    monkeypatch.delenv("NO_API_MODE", raising=False)
    run = run_evaluation(
        task_class=TASK,
        strategy=STRATEGIES["baseline"],
        cases=CASES,
        outputs=load_outputs(FIXTURES, "baseline"),
    )
    assert run.no_api_mode is True


def test_runner_rejects_mismatched_task_class() -> None:
    other = EvaluationCase("x", "1", "other@1", {}, {})
    with pytest.raises(ValueError):
        run_evaluation(
            task_class=TASK,
            strategy=STRATEGIES["baseline"],
            cases=[other],
            outputs={},
            no_api_mode_raw="true",
        )


# --- decisions ---------------------------------------------------------------


def test_a8_better_candidate_promotes_with_scope_and_rollback() -> None:
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_better")],
    )
    assert decision.decision is DecisionKind.PROMOTE
    assert decision.rollback_target == STRATEGIES["baseline"].identity
    assert decision.scope.startswith(TASK.identity)
    assert decision.evidence[0] == _run("baseline").run_id
    assert decision.requires_human_approval is False


def test_a6_policy_violation_is_rejected() -> None:
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_violating")],
    )
    assert decision.decision is DecisionKind.REJECT_SAFETY
    assert any(".github/workflows/harvest-ci.yml" in r for r in decision.rationale)


def test_a7_no_benefit_candidate_is_not_promoted_and_is_suppressed(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger = SuppressionLedger.load(ledger_path)
    first = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_nobenefit")],
        ledger=ledger,
    )
    assert first.decision is DecisionKind.REJECT_COST
    ledger.save(ledger_path)

    again = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_nobenefit")],
        ledger=SuppressionLedger.load(ledger_path),
    )
    assert again.suppressed_rediscovery is True
    assert again.decision is DecisionKind.REJECT_COST


def test_changed_candidate_is_not_suppressed(tmp_path) -> None:
    ledger = SuppressionLedger()
    decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_nobenefit")],
        ledger=ledger,
    )
    changed = run_evaluation(
        task_class=TASK,
        strategy=STRATEGIES["candidate_nobenefit"].__class__(
            **{**STRATEGIES["candidate_nobenefit"].__dict__, "version": "2"}
        ),
        cases=CASES,
        outputs=load_outputs(FIXTURES, "candidate_nobenefit"),
        no_api_mode_raw="true",
    )
    decision = decide(
        task_class=TASK, baseline=_run("baseline"), candidates=[changed], ledger=ledger
    )
    assert decision.suppressed_rediscovery is False


def test_promotion_is_never_suppressed() -> None:
    ledger = SuppressionLedger()
    decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_better")],
        ledger=ledger,
    )
    assert ledger.entries == {}


def test_equal_quality_with_unknown_cost_keeps_baseline() -> None:
    outputs = load_outputs(FIXTURES, "baseline")
    # An honestly unknown cost (pricing could not run), not a tampered estimate.
    outputs["c1-null-guard"]["receipt"]["cost"] = {
        "schema": "oc.execution-cost.v1",
        "basis": "unavailable",
        "billed_usd": None,
        "estimated_usd": None,
        "complete": False,
        "unpriced_reasons": ["pricing module unavailable"],
    }
    candidate = run_evaluation(
        task_class=TASK,
        strategy=STRATEGIES["candidate_nobenefit"],
        cases=CASES,
        outputs=outputs,
        no_api_mode_raw="true",
    )
    # An unpriced receipt is also less complete provenance, which the default
    # policy protects (and would reject on first); isolate the cost rule here.
    policy = PromotionPolicy(protected_metrics=("scope_compliance", "receipt_validity"))
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[candidate],
        policy=policy,
    )
    assert decision.decision is DecisionKind.KEEP_BASELINE
    assert "cost unmeasured" in decision.rationale[0]
    assert (
        decide(
            task_class=TASK, baseline=_run("baseline"), candidates=[candidate]
        ).decision
        is DecisionKind.REJECT_QUALITY
    )


def test_unmeasured_primary_metric_decides_nothing() -> None:
    outputs = load_outputs(FIXTURES, "candidate_better")
    for out in outputs.values():
        out.pop("checks")
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_better", outputs)],
    )
    assert decision.decision is DecisionKind.UNMEASURED


def test_replicates_that_disagree_are_unstable() -> None:
    other = load_outputs(FIXTURES, "candidate_better")
    other["c2-lexicon-schema"]["checks"][0]["conclusion"] = "failure"
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_better"), _run("candidate_better", other)],
    )
    assert decision.decision is DecisionKind.REJECT_INSTABILITY


def test_protected_metric_regression_rejects() -> None:
    outputs = load_outputs(FIXTURES, "candidate_better")
    for out in outputs.values():
        out["receipt"].pop("branch")
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_better", outputs)],
    )
    assert decision.decision is DecisionKind.REJECT_QUALITY
    assert "provenance_completeness" in decision.rationale[0]


def test_high_risk_class_promotes_only_to_canary_with_human_approval() -> None:
    high = EvaluationTaskClass(**{**TASK.__dict__, "risk_class": "high"})
    runs = [
        run_evaluation(
            task_class=high,
            strategy=STRATEGIES[n],
            cases=CASES,
            outputs=load_outputs(FIXTURES, n),
            no_api_mode_raw="true",
        )
        for n in ("baseline", "candidate_better")
    ]
    decision = decide(task_class=high, baseline=runs[0], candidates=[runs[1]])
    assert decision.decision is DecisionKind.LIMITED_CANARY
    assert decision.requires_human_approval is True
    assert (
        resolve_active_strategy(
            STRATEGIES["baseline"].identity, [decision], high.identity
        )
        == STRATEGIES["baseline"].identity
    )


def test_a9_a10_memory_summary_and_active_strategy() -> None:
    cand = _run("candidate_better")
    decision = decide(task_class=TASK, baseline=_run("baseline"), candidates=[cand])
    summary = memory_summary(decision, cand)
    assert summary["benefit"] == "measured_benefit"
    assert summary["strategy_fingerprint"] == cand.strategy_fingerprint
    assert "reasoning" not in json.dumps(summary)
    assert (
        resolve_active_strategy(
            STRATEGIES["baseline"].identity, [decision], TASK.identity
        )
        == STRATEGIES["candidate_better"].identity
    )
    rejected = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_violating")],
    )
    assert (
        resolve_active_strategy(
            STRATEGIES["baseline"].identity, [rejected], TASK.identity
        )
        == STRATEGIES["baseline"].identity
    )


def test_a12_decisions_authorize_nothing() -> None:
    for name in ("candidate_better", "candidate_violating", "candidate_nobenefit"):
        decision = decide(
            task_class=TASK, baseline=_run("baseline"), candidates=[_run(name)]
        )
        assert decision.authorizes == ()


def test_baseline_and_candidate_must_share_cases() -> None:
    fewer = [c for c in CASES if c.case_id != "c4-locality-redaction"]
    short = run_evaluation(
        task_class=TASK,
        strategy=STRATEGIES["candidate_better"],
        cases=fewer,
        outputs=load_outputs(FIXTURES, "candidate_better"),
        no_api_mode_raw="true",
    )
    with pytest.raises(ValueError):
        decide(task_class=TASK, baseline=_run("baseline"), candidates=[short])


def test_policy_thresholds_are_recorded() -> None:
    decision = decide(
        task_class=TASK,
        baseline=_run("baseline"),
        candidates=[_run("candidate_better")],
        policy=PromotionPolicy(),
    )
    assert decision.thresholds["min_improvement"] == "0.05"
    assert decision.thresholds["quality_floor"] == "0.5"


def test_cli_runs_offline(tmp_path, monkeypatch) -> None:
    import subprocess

    out = tmp_path / "report.json"
    ledger = tmp_path / "ledger.json"
    env = {"PYTHONPATH": str(REPO_ROOT), "NO_API_MODE": "true", "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oc_evals_run.py"), "--fixture-dir", str(FIXTURES),
         "--baseline", "baseline", "--candidate", "candidate_nobenefit", "--ledger", str(ledger), "--output", str(out)],
        capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text())
    assert report["decision"]["decision"] == "REJECT_COST"
    assert report["memory_summary"]["benefit"] == "no_benefit"
    assert json.loads(ledger.read_text())["entries"]
