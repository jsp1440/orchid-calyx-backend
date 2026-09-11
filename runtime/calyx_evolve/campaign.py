"""The bounded LEARN -> DESIGN -> EXPERIMENT -> ANALYZE -> REMEMBER loop.

One campaign owns one locked fixture, one baseline, and a set of candidates.
Running a candidate is idempotent: the runner derives a replay key first and
returns the stored record instead of re-executing, so repeated invocation
spends nothing and cannot produce a second, divergent history.

Architectural adaptation note: the learn/design/experiment/analyze/remember
staging follows the published ASI-Evolve pattern (arXiv:2603.29640; reference
implementation GAIR-NLP/ASI-Evolve, Apache-2.0).  No upstream code is copied or
vendored — every contract here is native Calyx (typed candidate configs, the
Calyx safety screen, the ``oc_admin`` ledger, and human-review-only promotion).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from runtime.calyx_evolve import analysis as analysis_module
from runtime.calyx_evolve.analysis import (
    ANALYZER_VERSION,
    Finding,
    analyze,
    blocking_findings,
    summarise,
)
from runtime.calyx_evolve.candidates import Candidate, deduplicate
from runtime.calyx_evolve.cognition import (
    CognitionBundle,
    CognitionItem,
    load_cognition,
)
from runtime.calyx_evolve.fixture import TaxonomyFixture, locked_fixture
from runtime.calyx_evolve.governance import (
    GOVERNANCE_DRAFT,
    PromotionProposal,
    assert_governance,
    build_promotion_proposal,
)
from runtime.calyx_evolve.memory import ExperimentMemory, replay_key
from runtime.calyx_evolve.metrics import (
    EVALUATOR_VERSION,
    METRIC_ACCURACY,
    METRIC_FALSE_MERGE_COUNT,
    METRIC_PROVENANCE,
    SCORING_VERSION,
    AggregateScore,
    MetricVector,
    aggregate_score,
    evaluate,
)
from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.reconciler import ReconciliationArtifact, run_reconciliation
from runtime.calyx_evolve.safety import (
    SCOPE_STAGING_ONLY,
    SafetyViolation,
    UnsafeCandidate,
    assert_safe_to_execute,
    is_eligible,
    is_promotable,
    provenance_violation,
    screen_output,
)
from runtime.calyx_evolve.sandbox import (
    ExperimentSandbox,
    SandboxLimitExceeded,
    SandboxLimits,
    SandboxTimeout,
    SandboxViolation,
)
from runtime.calyx_evolve.selection import (
    POLICY_BEST_ELIGIBLE,
    ScoredCandidate,
    build_selector,
)

TERMINAL_COMPLETED = "completed"
TERMINAL_REJECTED_UNSAFE = "rejected_unsafe"
TERMINAL_INELIGIBLE = "ineligible"
TERMINAL_EXECUTION_FAILED = "execution_failed"

TERMINAL_STATES: tuple[str, ...] = (
    TERMINAL_COMPLETED,
    TERMINAL_REJECTED_UNSAFE,
    TERMINAL_INELIGIBLE,
    TERMINAL_EXECUTION_FAILED,
)

LOOP_VERSION = "calyx-evolve-loop-1.0.0"


class CampaignError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True, slots=True)
class EvolveCampaign:
    campaign_id: str
    title: str
    baseline_candidate_id: str
    governance_state: str = GOVERNANCE_DRAFT
    execution_scope: str = SCOPE_STAGING_ONLY
    selection_policy: str = POLICY_BEST_ELIGIBLE
    selection_seed: int | None = None

    def __post_init__(self) -> None:
        assert_governance(self.governance_state, self.execution_scope)
        if not str(self.campaign_id).strip():
            raise CampaignError("campaign_id is required")
        if not str(self.baseline_candidate_id).strip():
            raise CampaignError("a campaign must name its baseline candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "title": self.title,
            "baseline_candidate_id": self.baseline_candidate_id,
            "governance_state": self.governance_state,
            "execution_scope": self.execution_scope,
            "selection_policy": self.selection_policy,
            "selection_seed": self.selection_seed,
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    run: dict[str, Any]
    reused: bool
    findings: tuple[Finding, ...]
    metrics: MetricVector | None
    score: AggregateScore | None
    proposal: PromotionProposal | None

    @property
    def run_id(self) -> str:
        return str(self.run["run_id"])

    @property
    def terminal_state(self) -> str:
        return str(self.run["terminal_state"])


@dataclass(frozen=True, slots=True)
class CycleReport:
    campaign_id: str
    cognition_bundle_hash: str
    results: tuple[RunResult, ...]
    duplicates: tuple[str, ...]
    selected_candidate_id: str | None
    selection_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "cognition_bundle_hash": self.cognition_bundle_hash,
            "loop_version": LOOP_VERSION,
            "runs": [
                {
                    "run_id": result.run_id,
                    "candidate_id": result.run["candidate_id"],
                    "terminal_state": result.terminal_state,
                    "reused": result.reused,
                    "eligible": result.run.get("eligible"),
                    "promotable": result.run.get("promotable"),
                    "score": result.run.get("aggregate_score", {}).get("value"),
                    "findings": summarise(result.findings),
                    "proposal_state": result.proposal.state if result.proposal else None,
                }
                for result in self.results
            ],
            "duplicate_candidates": list(self.duplicates),
            "selected_candidate_id": self.selected_candidate_id,
            "selection_policy": self.selection_policy,
        }


def _resolution_summary(artifact: ReconciliationArtifact) -> list[dict[str, Any]]:
    """Inspectable per-record summary that can never carry locality or secrets."""

    return [
        {
            "record_id": resolution.record_id,
            "outcome": resolution.outcome,
            "accepted_name": resolution.accepted_name,
            "rule": resolution.rule,
            "distance": resolution.distance,
            "provenance_complete": resolution.provenance_complete(),
        }
        for resolution in artifact.resolutions
    ]


@dataclass
class CampaignRunner:
    """Executes the loop against a durable :class:`ExperimentMemory`."""

    memory: ExperimentMemory
    fixture: TaxonomyFixture = field(default_factory=locked_fixture)
    clock: Callable[[], str] = utc_now
    monotonic: Callable[[], float] = time.monotonic
    sandbox_limits: SandboxLimits = field(default_factory=SandboxLimits)

    # --- LEARN ---------------------------------------------------------------

    def learn(self, campaign: EvolveCampaign, items: Iterable[CognitionItem]) -> CognitionBundle:
        """Validate cognition inputs and open (or refresh) the campaign record."""

        assert_governance(campaign.governance_state, campaign.execution_scope)
        bundle = load_cognition(items)

        record = campaign.to_dict()
        record.update(
            {
                "loop_version": LOOP_VERSION,
                "evaluator_version": EVALUATOR_VERSION,
                "scoring_version": SCORING_VERSION,
                "analyzer_version": ANALYZER_VERSION,
                "fixture": self.fixture.descriptor(),
                "cognition_bundle_hash": bundle.bundle_hash,
                "cognition_item_count": len(bundle.items),
                "opened_at": self.clock(),
            }
        )
        record["record_hash"] = content_hash(record)
        self.memory.upsert_campaign(record)
        self.memory.record_cognition(
            campaign.campaign_id, [item.to_dict() for item in bundle.items]
        )
        return bundle

    # --- DESIGN --------------------------------------------------------------

    def design(
        self, campaign: EvolveCampaign, candidates: Sequence[Candidate]
    ) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
        """Register candidates, returning ``(registered, duplicates)``.

        Duplicates are candidates whose novelty key already exists in durable
        memory (including refuted ones) — the loop records them and moves on
        rather than re-spending on a strategy it has already evaluated.
        """

        for candidate in candidates:
            if candidate.campaign_id != campaign.campaign_id:
                raise CampaignError(
                    f"candidate {candidate.candidate_id!r} belongs to campaign "
                    f"{candidate.campaign_id!r}, not {campaign.campaign_id!r}"
                )

        fresh, in_batch_duplicates = deduplicate(candidates)

        registered: list[Candidate] = []
        duplicates: list[Candidate] = list(in_batch_duplicates)
        for candidate in fresh:
            existing = self.memory.find_candidate_by_novelty(
                campaign.campaign_id, candidate.novelty_key
            )
            if existing is not None and existing["candidate_id"] != candidate.candidate_id:
                duplicates.append(candidate)
                continue
            record = candidate.to_dict()
            record["registered_at"] = self.clock()
            record["record_hash"] = content_hash(candidate.to_dict())
            self.memory.upsert_candidate(record)
            registered.append(candidate)

        return tuple(registered), tuple(duplicates)

    # --- EXPERIMENT + ANALYZE + REMEMBER -------------------------------------

    def experiment(
        self,
        campaign: EvolveCampaign,
        candidate: Candidate,
        *,
        baseline_metrics: MetricVector | None = None,
        baseline_score: AggregateScore | None = None,
    ) -> RunResult:
        """Run one candidate idempotently and persist the complete record."""

        assert_governance(campaign.governance_state, campaign.execution_scope)

        key = replay_key(
            campaign_id=campaign.campaign_id,
            config_hash=candidate.config.config_hash,
            fixture_hash=self.fixture.fixture_hash,
            evaluator_version=EVALUATOR_VERSION,
            scoring_version=SCORING_VERSION,
            baseline_candidate_id=campaign.baseline_candidate_id,
        )
        existing = self.memory.find_run_by_replay_key(key)
        if existing is not None:
            return self._rehydrate(existing)

        run_id = "run-" + key.split(":", 1)[1][:24]
        started_at = self.clock()

        base_record: dict[str, Any] = {
            "run_id": run_id,
            "campaign_id": campaign.campaign_id,
            "candidate_id": candidate.candidate_id,
            "replay_key": key,
            "loop_version": LOOP_VERSION,
            "evaluator_version": EVALUATOR_VERSION,
            "scoring_version": SCORING_VERSION,
            "analyzer_version": ANALYZER_VERSION,
            "execution_scope": campaign.execution_scope,
            "governance_state": campaign.governance_state,
            "baseline_candidate_id": campaign.baseline_candidate_id,
            "config_hash": candidate.config.config_hash,
            "novelty_key": candidate.novelty_key,
            "parent_ids": list(candidate.parent_ids),
            "fixture": self.fixture.descriptor(),
            "sandbox": self.sandbox_limits.to_dict(),
            "started_at": started_at,
        }

        # Pre-execution safety screen: a mutation or activation request never runs.
        try:
            assert_safe_to_execute(candidate, execution_scope=campaign.execution_scope)
        except UnsafeCandidate as unsafe:
            return self._finish_unsafe(campaign, candidate, base_record, unsafe.violations)

        sandbox = ExperimentSandbox(limits=self.sandbox_limits, monotonic=self.monotonic).start()
        elapsed_start = self.monotonic()
        try:
            artifact = run_reconciliation(candidate.config, self.fixture, sandbox)
        except (SandboxTimeout, SandboxLimitExceeded, SandboxViolation) as exc:
            return self._finish_failed(campaign, candidate, base_record, exc)
        runtime_seconds = max(0.0, self.monotonic() - elapsed_start)

        replay_sandbox = ExperimentSandbox(
            limits=self.sandbox_limits, monotonic=self.monotonic
        ).start()
        replay_artifact = run_reconciliation(candidate.config, self.fixture, replay_sandbox)
        replay_deterministic = replay_artifact.artifact_digest == artifact.artifact_digest

        violations: list[SafetyViolation] = list(screen_output(artifact.to_dict()))

        vector = evaluate(
            artifact,
            self.fixture,
            runtime_seconds=round(runtime_seconds, 6),
            replay_deterministic=replay_deterministic,
            declared_cost_usd=candidate.declared_cost_usd,
            cost_basis=candidate.cost_basis,
        )
        score = aggregate_score(vector)

        provenance_metric = vector.as_mapping().get(METRIC_PROVENANCE)
        provenance_flag = provenance_violation(
            provenance_metric.value if provenance_metric and provenance_metric.is_measured else None
        )
        if provenance_flag is not None:
            violations.append(provenance_flag)

        false_merges = vector.as_mapping().get(METRIC_FALSE_MERGE_COUNT)
        eligible = is_eligible(violations)
        promotable = (
            is_promotable(violations)
            and score.value is not None
            and false_merges is not None
            and false_merges.is_measured
            and false_merges.numeric() == 0
        )

        findings = analyze(
            run_id=run_id,
            candidate_metrics=vector,
            baseline_metrics=baseline_metrics,
            candidate_score=score,
            baseline_score=baseline_score,
            violations=tuple(violations),
        )

        record = dict(base_record)
        record.update(
            {
                "terminal_state": TERMINAL_COMPLETED if eligible else TERMINAL_INELIGIBLE,
                "completed_at": self.clock(),
                "runtime_seconds": round(runtime_seconds, 6),
                "artifact_digest": artifact.artifact_digest,
                "replay_artifact_digest": replay_artifact.artifact_digest,
                "replay_deterministic": replay_deterministic,
                "resolutions": _resolution_summary(artifact),
                "metric_vector": vector.to_dict(),
                "aggregate_score": score.to_dict(),
                "safety_violations": [v.to_dict() for v in violations],
                "eligible": eligible,
                "promotable": bool(promotable),
                "finding_counts": summarise(findings),
            }
        )
        baseline_value = baseline_score.value if baseline_score is not None else None
        improved = (
            score.value is not None
            and baseline_value is not None
            and score.value > baseline_value
        )
        record["improved_over_baseline"] = bool(improved)
        proposal = self._propose(
            campaign, candidate, record, vector, findings, promotable, improved
        )
        if proposal is not None:
            record["promotion_proposal_id"] = proposal.proposal_id
            record["promotion_state"] = proposal.state
        else:
            record["promotion_state"] = "not_proposed"

        record["record_hash"] = content_hash(
            {
                k: v
                for k, v in record.items()
                if k
                not in {"record_hash", "started_at", "completed_at", "runtime_seconds", "metric_vector"}
            }
        )

        self.memory.save_run(record)
        self.memory.save_metrics(run_id, [value.to_dict() for value in vector.values])
        self.memory.save_findings(run_id, [finding.to_dict() for finding in findings])
        if proposal is not None:
            self.memory.save_proposal(proposal.to_dict())

        return RunResult(
            run=record,
            reused=False,
            findings=findings,
            metrics=vector,
            score=score,
            proposal=proposal,
        )

    # --- helpers -------------------------------------------------------------

    def _propose(
        self,
        campaign: EvolveCampaign,
        candidate: Candidate,
        record: Mapping[str, Any],
        vector: MetricVector,
        findings: tuple[Finding, ...],
        promotable: bool,
        improved: bool,
    ) -> PromotionProposal | None:
        """Build a promotion proposal for a candidate that beat its baseline.

        Only an improvement over the locked baseline is a result worth reviewing,
        so a candidate that merely ran produces no proposal.  The baseline itself
        is never proposed, and success never produces anything stronger than
        ``review_pending``.
        """

        if candidate.is_baseline or not improved:
            return None

        blockers = [
            f"{finding.finding_type}:{finding.code}" for finding in blocking_findings(findings)
        ]
        if not promotable and not blockers:
            blockers.append("failure:NOT_PROMOTABLE")

        mapping = vector.as_mapping()
        metric_summary = {
            key: mapping[key].to_dict()
            for key in (METRIC_ACCURACY, METRIC_FALSE_MERGE_COUNT, METRIC_PROVENANCE)
            if key in mapping
        }
        metric_summary["aggregate_score"] = dict(record.get("aggregate_score", {}))

        rationale = (
            f"Candidate {candidate.candidate_id} completed the locked "
            f"{self.fixture.fixture_id} experiment under evaluator {EVALUATOR_VERSION}. "
            "Human scientific review is required before any taxonomy change."
        )
        return build_promotion_proposal(
            campaign_id=campaign.campaign_id,
            run_id=str(record["run_id"]),
            candidate_id=candidate.candidate_id,
            blockers=blockers,
            rationale=rationale,
            metric_summary=metric_summary,
            created_at=self.clock(),
        )

    def _finish_unsafe(
        self,
        campaign: EvolveCampaign,
        candidate: Candidate,
        base_record: dict[str, Any],
        violations: tuple[SafetyViolation, ...],
    ) -> RunResult:
        record = dict(base_record)
        record.update(
            {
                "terminal_state": TERMINAL_REJECTED_UNSAFE,
                "completed_at": self.clock(),
                "runtime_seconds": 0.0,
                "artifact_digest": None,
                "replay_deterministic": None,
                "resolutions": [],
                "metric_vector": None,
                "aggregate_score": None,
                "safety_violations": [v.to_dict() for v in violations],
                "eligible": False,
                "promotable": False,
                "executed": False,
                "finding_counts": {},
            }
        )
        findings = tuple(
            Finding(
                run_id=str(record["run_id"]),
                finding_type=analysis_module.FINDING_COUNTEREVIDENCE,
                code=violation.code,
                summary=violation.detail,
                severity=analysis_module.SEVERITY_BLOCKING,
                evidence=violation.to_dict(),
            )
            for violation in violations
        )
        record["finding_counts"] = summarise(findings)
        record["record_hash"] = content_hash(
            {k: v for k, v in record.items() if k not in {"record_hash", "started_at", "completed_at"}}
        )

        # A candidate that never executed produced no result, so there is
        # nothing to propose.  The run record and its blocking findings are the
        # durable evidence that the request was refused.
        record["promotion_state"] = "not_proposed"

        self.memory.save_run(record)
        self.memory.save_findings(record["run_id"], [f.to_dict() for f in findings])

        return RunResult(
            run=record, reused=False, findings=findings, metrics=None, score=None, proposal=None
        )

    def _finish_failed(
        self,
        campaign: EvolveCampaign,
        candidate: Candidate,
        base_record: dict[str, Any],
        exc: Exception,
    ) -> RunResult:
        violation = SafetyViolation(
            code=type(exc).__name__,
            disposition="ineligible",
            detail=str(exc)[:400],
        )
        record = dict(base_record)
        record.update(
            {
                "terminal_state": TERMINAL_EXECUTION_FAILED,
                "completed_at": self.clock(),
                "artifact_digest": None,
                "replay_deterministic": None,
                "resolutions": [],
                "metric_vector": None,
                "aggregate_score": None,
                "safety_violations": [violation.to_dict()],
                "eligible": False,
                "promotable": False,
                "executed": True,
                "promotion_state": "not_proposed",
            }
        )
        findings = (
            Finding(
                run_id=str(record["run_id"]),
                finding_type=analysis_module.FINDING_FAILURE,
                code="EXECUTION_BOUND_EXCEEDED",
                summary=str(exc)[:400],
                severity=analysis_module.SEVERITY_BLOCKING,
                evidence=violation.to_dict(),
            ),
        )
        record["finding_counts"] = summarise(findings)
        record["record_hash"] = content_hash(
            {k: v for k, v in record.items() if k not in {"record_hash", "started_at", "completed_at"}}
        )
        self.memory.save_run(record)
        self.memory.save_findings(record["run_id"], [f.to_dict() for f in findings])
        return RunResult(
            run=record, reused=False, findings=findings, metrics=None, score=None, proposal=None
        )

    def _rehydrate(self, record: Mapping[str, Any]) -> RunResult:
        """Return a stored run without re-executing or re-spending anything."""

        run_id = str(record["run_id"])
        findings = tuple(
            Finding(
                run_id=run_id,
                finding_type=str(row["finding_type"]),
                code=str(row["code"]),
                summary=str(row["summary"]),
                severity=str(row.get("severity", analysis_module.SEVERITY_INFO)),
                evidence=dict(row.get("evidence", {})),
            )
            for row in self.memory.list_findings(run_id)
        )
        proposals = [
            row
            for row in self.memory.list_proposals(str(record["campaign_id"]))
            if row.get("run_id") == run_id
        ]
        proposal = None
        if proposals:
            stored = proposals[0]
            proposal = PromotionProposal(
                campaign_id=str(stored["campaign_id"]),
                run_id=str(stored["run_id"]),
                candidate_id=str(stored["candidate_id"]),
                state=str(stored["state"]),
                rationale=str(stored["rationale"]),
                blockers=tuple(stored.get("blockers", ())),
                metric_summary=dict(stored.get("metric_summary", {})),
                created_at=str(stored.get("created_at", "")),
            )
        return RunResult(
            run=dict(record),
            reused=True,
            findings=findings,
            metrics=None,
            score=None,
            proposal=proposal,
        )

    # --- full cycle ----------------------------------------------------------

    def cycle(
        self,
        campaign: EvolveCampaign,
        cognition_items: Iterable[CognitionItem],
        candidates: Sequence[Candidate],
    ) -> CycleReport:
        """Run one complete loop pass and select a candidate."""

        bundle = self.learn(campaign, cognition_items)
        registered, duplicates = self.design(campaign, candidates)

        by_id = {candidate.candidate_id: candidate for candidate in registered}
        baseline = by_id.get(campaign.baseline_candidate_id)
        if baseline is None:
            raise CampaignError(
                f"baseline candidate {campaign.baseline_candidate_id!r} was not registered"
            )

        baseline_result = self.experiment(campaign, baseline)
        baseline_metrics = baseline_result.metrics
        baseline_score = baseline_result.score

        results: list[RunResult] = [baseline_result]
        for candidate in registered:
            if candidate.candidate_id == baseline.candidate_id:
                continue
            results.append(
                self.experiment(
                    campaign,
                    candidate,
                    baseline_metrics=baseline_metrics,
                    baseline_score=baseline_score,
                )
            )

        scored = [
            ScoredCandidate(
                candidate_id=str(result.run["candidate_id"]),
                run_id=result.run_id,
                is_baseline=str(result.run["candidate_id"]) == campaign.baseline_candidate_id,
                eligible=bool(result.run.get("eligible")),
                score=(result.run.get("aggregate_score") or {}).get("value"),
                ineligibility_reasons=tuple(
                    str(v.get("code")) for v in result.run.get("safety_violations", [])
                ),
            )
            for result in results
        ]
        selector = build_selector(campaign.selection_policy, seed=campaign.selection_seed)
        selected = selector.select(scored)

        return CycleReport(
            campaign_id=campaign.campaign_id,
            cognition_bundle_hash=bundle.bundle_hash,
            results=tuple(results),
            duplicates=tuple(candidate.candidate_id for candidate in duplicates),
            selected_candidate_id=selected.candidate_id if selected else None,
            selection_policy=campaign.selection_policy,
        )
