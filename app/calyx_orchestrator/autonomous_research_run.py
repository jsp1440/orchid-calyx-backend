"""Autonomous research run conductor — the loop that ties all links together.

This is the top-level orchestrator in the autonomous research execution loop:

    RunEvidenceManifest + GovernanceDecision
    → decompose_governed_action()        (ResearchBlueprint)
    → enqueue_blueprint()                (tasks registered in reservoir)
    → BoundedDispatcher.run()            (DispatchRun)
    → build_blueprint_run_report()       (BlueprintRunReport)
      ┌── run_status == "all_complete"    → collect evidence → AutonomousRunReport (DONE)
      ├── run_status == "partially_blocked" → collect evidence → AutonomousRunReport (DONE)
      ├── run_status == "awaiting_owner_gate" → yield GatePendingRecord (NEEDS OWNER)
      └── run_status == "in_progress"    → re-trigger dispatcher (iterate)

Hard constraints:
  - max_dispatch_rounds prevents infinite loops (default 5).
  - Provider-free: DeterministicResearchWorker only; zero paid API calls.
  - GovernanceDecision must be ADMITTED; rejected manifests are refused immediately.
  - The conductor does not auto-approve OWNER_GATED tasks; gate decisions are
    the caller's responsibility (via OwnerAuthorizationGate).

Contract:
  - `AutonomousResearchRun.execute()` → AutonomousRunReport
  - If any OWNER_GATED tasks remain after all dispatch rounds, run_status is
    "awaiting_owner_gate" and owner_gate_pending lists the blocking tasks.
  - The final BlueprintRunReport and DispatchRun are always preserved in the report.
  - All evidence from completed task leaves is collected into run_evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.scientific_synthesis.blueprint import (
    decompose_governed_action,
    enqueue_blueprint,
    validate_blueprint,
)

from .blueprint_run_report import BlueprintRunReport, build_blueprint_run_report
from .bounded_dispatcher import BoundedDispatcher, DispatchConfig, DispatchRun
from .deep_orchestrate import DeepOrchestrate, TaskState
from .leaf_worker import DeterministicResearchWorker

log = logging.getLogger(__name__)

RUN_VERSION = "oc-autonomous-research-run-v1"
_DEFAULT_MAX_DISPATCH_ROUNDS = 5


@dataclass(frozen=True, slots=True)
class AutonomousRunReport:
    """Final result of a completed (or gate-paused) autonomous research run.

    Fields
    ------
    run_id              Caller-supplied identifier for this run.
    blueprint_id        Fingerprint of the decomposed ResearchBlueprint.
    run_status          Terminal or gate-paused status:
                          "all_complete"        — every task COMPLETED
                          "partially_blocked"   — some tasks BLOCKED; rest done
                          "awaiting_owner_gate" — one or more OWNER_GATED tasks
                                                  remain; owner must resume via
                                                  OwnerAuthorizationGate
                          "dispatch_limit_reached" — max_dispatch_rounds exhausted
                                                  before reaching a terminal state
    owner_gate_pending  Task provenance dicts for tasks still in OWNER_GATED state.
    run_evidence        Evidence collected from every COMPLETED task leaf.
    dispatch_rounds     Number of dispatcher iterations executed.
    final_report        The BlueprintRunReport produced after the last round.
    last_dispatch_run   The DispatchRun from the last dispatcher invocation.
    tasks_executed      Total tasks executed across all rounds.
    version             Schema version.
    generated_at_utc    ISO-8601 UTC timestamp.
    """

    run_id: str
    blueprint_id: str
    run_status: str
    owner_gate_pending: tuple[dict[str, Any], ...]
    run_evidence: tuple[dict[str, Any], ...]
    dispatch_rounds: int
    final_report: BlueprintRunReport
    last_dispatch_run: DispatchRun
    tasks_executed: int
    version: str
    generated_at_utc: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "blueprint_id": self.blueprint_id,
            "run_status": self.run_status,
            "owner_gate_pending": list(self.owner_gate_pending),
            "run_evidence": list(self.run_evidence),
            "dispatch_rounds": self.dispatch_rounds,
            "tasks_executed": self.tasks_executed,
            "final_report": self.final_report.as_dict(),
            "last_dispatch_run": self.last_dispatch_run.summary(),
            "generated_at_utc": self.generated_at_utc,
        }


class AutonomousResearchRun:
    """Conduct the full autonomous research execution loop end-to-end.

    Usage::

        run = AutonomousResearchRun(
            reservoir=DeepOrchestrate(configured_width=8),
            worker=DeterministicResearchWorker(),
        )
        report = run.execute(
            manifest=manifest_dict,
            governance_decision=decision,
            proposed_action="build_synthesis",
            run_id="run-001",
            taxon_id="taxon:orchidaceae",
            research_question="What is the common name?",
        )
        print(report.run_status)  # "all_complete" | "partially_blocked" | ...
    """

    def __init__(
        self,
        reservoir: DeepOrchestrate,
        worker: DeterministicResearchWorker | None = None,
        max_dispatch_rounds: int = _DEFAULT_MAX_DISPATCH_ROUNDS,
    ) -> None:
        self.reservoir = reservoir
        self.worker = worker or DeterministicResearchWorker()
        self.max_dispatch_rounds = max_dispatch_rounds

    def execute(
        self,
        manifest: dict[str, Any],
        governance_decision: Any,
        proposed_action: str,
        *,
        run_id: str,
        taxon_id: str,
        research_question: str,
        dispatch_config: DispatchConfig | None = None,
    ) -> AutonomousRunReport:
        """Run the complete autonomous research loop.

        Parameters
        ----------
        manifest            RunEvidenceManifest dict (from build_run_evidence_manifest).
        governance_decision GovernanceDecision; must be ADMITTED.
        proposed_action     String label for the research action (e.g. "build_synthesis").
        run_id              Caller-supplied run identifier.
        taxon_id            Taxon being researched.
        research_question   The research question driving this run.
        dispatch_config     Optional dispatcher config; defaults to DispatchConfig().
        """
        if not governance_decision.admitted:
            raise ValueError(
                f"GOVERNANCE_REJECTED:{governance_decision.outcome}:"
                f"{governance_decision.reason}"
            )

        # --- Step 1: Decompose governance decision into blueprint + enqueue tasks ---
        blueprint = decompose_governed_action(
            governance_decision,
            manifest,
            proposed_action,
            run_id=run_id,
            taxon_id=taxon_id,
            research_question=research_question,
        )
        validate_blueprint(blueprint)
        enqueued = enqueue_blueprint(blueprint, self.reservoir)
        log.info(
            "autonomous_run.enqueued run_id=%s blueprint_id=%s tasks=%d",
            run_id,
            blueprint.blueprint_id[:12],
            enqueued,
        )

        cfg = dispatch_config or DispatchConfig()
        dispatcher = BoundedDispatcher(self.reservoir, worker=self.worker)

        last_run: DispatchRun | None = None
        last_report: BlueprintRunReport | None = None
        total_executed = 0
        rounds = 0

        # --- Step 2: Iterative dispatch until terminal state or round limit ---
        for round_num in range(1, self.max_dispatch_rounds + 1):
            rounds = round_num
            dispatch_run = dispatcher.run(cfg)
            last_run = dispatch_run
            total_executed += dispatch_run.tasks_executed

            report = build_blueprint_run_report(blueprint, dispatch_run, self.reservoir)
            last_report = report

            log.info(
                "autonomous_run.round run_id=%s round=%d/%d status=%s executed=%d",
                run_id,
                round_num,
                self.max_dispatch_rounds,
                report.run_status,
                dispatch_run.tasks_executed,
            )

            if report.run_status in ("all_complete", "partially_blocked"):
                break
            if report.run_status == "awaiting_owner_gate":
                break
            # "in_progress" — continue; dispatcher made some progress or recovered leases.
            if dispatch_run.tasks_executed == 0 and dispatch_run.expired_recovered == 0:
                # No progress this round — avoid spinning; treat as dispatch_limit.
                rounds = self.max_dispatch_rounds
                break

        assert last_run is not None
        assert last_report is not None

        # --- Step 3: Collect evidence from all COMPLETED task leaves ---
        run_evidence: list[dict[str, Any]] = []
        for leaf_meta in blueprint.task_leaves:
            live = self.reservoir.get(leaf_meta.key)
            if live is not None and live.state == TaskState.COMPLETED and live.evidence:
                run_evidence.append({
                    "task_key": live.key,
                    "title": live.title,
                    "authority_class": live.authority_class,
                    "evidence": live.evidence,
                })

        # Determine final status
        if last_report.run_status in ("all_complete", "partially_blocked", "awaiting_owner_gate"):
            final_status = last_report.run_status
        else:
            final_status = "dispatch_limit_reached"

        return AutonomousRunReport(
            run_id=run_id,
            blueprint_id=blueprint.blueprint_id,
            run_status=final_status,
            owner_gate_pending=tuple(last_report.owner_gated_pending),
            run_evidence=tuple(run_evidence),
            dispatch_rounds=rounds,
            final_report=last_report,
            last_dispatch_run=last_run,
            tasks_executed=total_executed,
            version=RUN_VERSION,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
        )
