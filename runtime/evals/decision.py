"""Promotion gate, suppression and active-strategy resolution (EVALS-001D, first slice).

Implements the OC-EVALS-001 promotion policy over two or more evaluation runs:

1. any mandatory safety/integrity gate failure rejects (REJECT_SAFETY);
2. replicate runs of the candidate must agree (else REJECT_INSTABILITY);
3. an unmeasured primary metric cannot justify anything (UNMEASURED);
4. the candidate must meet the task class quality floor (REJECT_QUALITY);
5. no protected metric may regress beyond tolerance (REJECT_QUALITY);
6. it must improve the primary metric, or match it at materially lower
   *known* cost (PROMOTE); an unknown cost is never a saving;
7. otherwise the baseline stays (KEEP_BASELINE), or a costlier candidate with
   no quality gain is rejected (REJECT_COST).

High-risk task classes never promote directly: a passing candidate becomes a
LIMITED_CANARY that requires human approval. A decision authorizes nothing
outside the evaluation layer -- no merge, deploy, publication, or provider
activation follows from it.

The suppression ledger is a JSON document (no database): an unchanged candidate
that was already rejected or found no-benefit is not re-evaluated.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from runtime.evals.contracts import (
    DecisionKind,
    EvaluationRun,
    EvaluationTaskClass,
    StrategyDecision,
    fingerprint,
)

SUPPRESSIBLE = {
    DecisionKind.KEEP_BASELINE,
    DecisionKind.REJECT_QUALITY,
    DecisionKind.REJECT_SAFETY,
    DecisionKind.REJECT_COST,
    DecisionKind.REJECT_INSTABILITY,
}


@dataclass(frozen=True)
class PromotionPolicy:
    min_improvement: Decimal = Decimal("0.05")
    equivalence_tolerance: Decimal = Decimal("0.01")
    regression_tolerance: Decimal = Decimal("0.02")
    min_cost_reduction: Decimal = Decimal("0.20")  # fraction of baseline cost
    max_cost_increase: Decimal = Decimal("0.50")
    protected_metrics: tuple[str, ...] = (
        "scope_compliance",
        "receipt_validity",
        "provenance_completeness",
    )
    review_trigger: str = (
        "retest on evaluator, pricing, case-set or model change, or after 30 days"
    )

    def as_thresholds(self) -> dict[str, str]:
        return {k: str(v) for k, v in self.__dict__.items() if not isinstance(v, tuple)}


DEFAULT_POLICY = PromotionPolicy()


def suppression_key(task_class: str, candidate_run: EvaluationRun) -> str:
    return fingerprint(
        {
            "task_class": task_class,
            "candidate": candidate_run.strategy_fingerprint,
            "cases": candidate_run.case_set_fingerprint,
            "evaluators": candidate_run.evaluator_versions,
        }
    )


@dataclass
class SuppressionLedger:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> SuppressionLedger:
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "oc.evals.suppression-ledger.v1":
            raise ValueError("wrong suppression ledger schema")
        return cls(dict(payload.get("entries") or {}))

    def save(self, path: Path) -> None:
        payload = {"schema": "oc.evals.suppression-ledger.v1", "entries": self.entries}
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def record(self, key: str, decision: StrategyDecision) -> None:
        if decision.decision in SUPPRESSIBLE:
            self.entries[key] = {
                "decision": decision.decision.value,
                "candidate": decision.candidate,
                "evidence": list(decision.evidence),
            }


def _primary(run: EvaluationRun, metric: str) -> Decimal | None:
    summary = run.summary(metric)
    return summary.mean_score if summary else None


def decide(
    *,
    task_class: EvaluationTaskClass,
    baseline: EvaluationRun,
    candidates: Sequence[EvaluationRun],
    policy: PromotionPolicy = DEFAULT_POLICY,
    ledger: SuppressionLedger | None = None,
) -> StrategyDecision:
    if not candidates:
        raise ValueError("at least one candidate run is required")
    candidate = candidates[0]
    for run in (baseline, *candidates):
        if run.task_class != task_class.identity:
            raise ValueError(f"run {run.run_id[:12]} is for {run.task_class}")
        if run.case_set_fingerprint != baseline.case_set_fingerprint:
            raise ValueError(
                "baseline and candidate must run on the same frozen case set"
            )
        if run.evaluator_versions != baseline.evaluator_versions:
            raise ValueError(
                "baseline and candidate must use the same evaluator versions"
            )
    if len({run.strategy for run in candidates}) != 1:
        raise ValueError("candidate replicates must be the same strategy")

    key = suppression_key(task_class.identity, candidate)

    def make(
        kind: DecisionKind, *rationale: str, suppressed: bool = False
    ) -> StrategyDecision:
        human = task_class.risk_class == "high" and kind is DecisionKind.PROMOTE
        decision = StrategyDecision(
            decision=DecisionKind.LIMITED_CANARY if human else kind,
            task_class=task_class.identity,
            baseline=baseline.strategy,
            candidate=candidate.strategy,
            rationale=rationale
            + (
                (
                    "high-risk task class: promotion limited to canary pending human approval",
                )
                if human
                else ()
            ),
            thresholds={
                **policy.as_thresholds(),
                "quality_floor": str(task_class.quality_floor),
            },
            evidence=(baseline.run_id, *(run.run_id for run in candidates)),
            scope=f"{task_class.identity} on case set {baseline.case_set_fingerprint[:12]}",
            rollback_target=baseline.strategy,
            review_trigger=policy.review_trigger,
            requires_human_approval=human,
            suppressed_rediscovery=suppressed,
        )
        if ledger is not None and not suppressed:
            ledger.record(key, decision)
        return decision

    if ledger is not None and key in ledger.entries:
        prior = ledger.entries[key]
        return make(
            DecisionKind(prior["decision"]),
            f"unchanged candidate already decided {prior['decision']} on this case set and evaluator suite; not re-evaluated",
            suppressed=True,
        )

    gate_failures = [r for run in candidates for r in run.gate_failures]
    if gate_failures:
        return make(
            DecisionKind.REJECT_SAFETY,
            *sorted(
                {
                    f"{r.metric_id} failed on {r.case_id}: {'; '.join(r.reasons)}"
                    for r in gate_failures
                }
            ),
        )

    if (
        len({run.outputs_fingerprint for run in candidates}) > 1
        or len({run.summaries for run in candidates}) > 1
    ):
        return make(
            DecisionKind.REJECT_INSTABILITY,
            "candidate replicates disagree on the frozen case set",
        )

    metric = task_class.primary_metric
    base_score, cand_score = _primary(baseline, metric), _primary(candidate, metric)
    if base_score is None or cand_score is None:
        return make(
            DecisionKind.UNMEASURED,
            f"primary metric {metric} is unmeasured for baseline or candidate",
        )

    if cand_score < task_class.quality_floor:
        return make(
            DecisionKind.REJECT_QUALITY,
            f"{metric} {cand_score} below floor {task_class.quality_floor}",
        )

    for protected in policy.protected_metrics:
        b, c = _primary(baseline, protected), _primary(candidate, protected)
        if b is not None and c is not None and c < b - policy.regression_tolerance:
            return make(
                DecisionKind.REJECT_QUALITY,
                f"protected metric {protected} regressed {b} -> {c}",
            )

    delta = cand_score - base_score
    if delta >= policy.min_improvement:
        return make(
            DecisionKind.PROMOTE, f"{metric} improved {base_score} -> {cand_score}"
        )

    base_cost, cand_cost = baseline.estimated_cost_usd, candidate.estimated_cost_usd
    if abs(delta) <= policy.equivalence_tolerance:
        if base_cost is None or cand_cost is None:
            return make(
                DecisionKind.KEEP_BASELINE,
                "equivalent quality; cost unmeasured, so no measured benefit",
            )
        if (
            base_cost > 0
            and (base_cost - cand_cost) / base_cost >= policy.min_cost_reduction
        ):
            return make(
                DecisionKind.PROMOTE,
                f"equivalent quality at lower estimated cost {base_cost} -> {cand_cost}",
            )
        if (
            base_cost > 0
            and (cand_cost - base_cost) / base_cost > policy.max_cost_increase
        ):
            return make(
                DecisionKind.REJECT_COST,
                f"no quality gain at higher estimated cost {base_cost} -> {cand_cost}",
            )
    return make(
        DecisionKind.KEEP_BASELINE,
        f"no measured benefit: {metric} {base_score} -> {cand_score}",
    )


def memory_summary(
    decision: StrategyDecision, candidate: EvaluationRun
) -> dict[str, Any]:
    """Outcome summary shaped for Scientific Memory: measured facts, no reasoning trace.

    NOT INTEGRATED: this returns a record; nothing persists it to Scientific
    Memory yet (OC-EVALS-001 acceptance 9 / EVALS-001D remain open).
    """
    return {
        "schema": "oc.evals.memory-summary.v1",
        "task_class": decision.task_class,
        "strategy": decision.candidate,
        "strategy_fingerprint": candidate.strategy_fingerprint,
        "evaluator_versions": [list(v) for v in candidate.evaluator_versions],
        "case_set_fingerprint": candidate.case_set_fingerprint,
        "outcome": decision.decision.value,
        "benefit": {
            DecisionKind.PROMOTE: "measured_benefit",
            DecisionKind.LIMITED_CANARY: "measured_benefit_pending_review",
            DecisionKind.UNMEASURED: "unmeasured",
        }.get(decision.decision, "no_benefit"),
        "review_trigger": decision.review_trigger,
        "evidence": list(decision.evidence),
    }


def resolve_active_strategy(
    baseline: str, decisions: Sequence[StrategyDecision], task_class: str
) -> str:
    """The strategy the orchestrator should use for a task class.

    NOT INTEGRATED: no orchestrator, scheduler or router calls this yet
    (OC-EVALS-001 acceptance 10 / EVALS-001C remain open).

    The latest PROMOTE for the class wins; canaries and rejections leave the
    baseline (or the previously promoted strategy) active.
    """
    active = baseline
    for decision in decisions:
        if (
            decision.task_class == task_class
            and decision.decision is DecisionKind.PROMOTE
        ):
            active = decision.candidate
    return active
