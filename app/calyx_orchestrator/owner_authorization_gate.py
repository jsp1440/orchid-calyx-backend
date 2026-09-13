"""Owner authorization gate for OWNER_GATED tasks in the autonomous research loop.

This is the next link after BlueprintRunReport in the autonomous research loop:

    BlueprintRunReport(run_status="awaiting_owner_gate")
    → OwnerAuthorizationGate.authorize(decisions)
    → OwnerAuthorizationResult
    → BoundedDispatcher.run()  (re-triggered for newly authorized tasks)
    → BlueprintRunReport (updated — terminal state)

This gate enforces the hard invariant that OWNER_GATED tasks (those requiring
AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, or AUTH_GOVERNANCE authority)
NEVER auto-execute. Every such task must receive an explicit per-task authorization
decision from an identified owner before it transitions to READY.

Contract:
  - Only tasks listed in report.owner_gated_pending may be authorized.
  - Approved tasks: reservoir.authorize(key) → READY → dispatcher executes.
  - Denied tasks: left as OWNER_GATED; no state mutation.
  - Unknown tasks (not in owner_gated_pending): silently ignored.
  - Authorizing an already-COMPLETED or already-READY task is a no-op (idempotent).
  - Zero paid provider calls. Fully deterministic.

Caller is responsible for authenticating the owner identity before calling authorize().
This module records the approver identity in provenance but does not re-authenticate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .blueprint_run_report import BlueprintRunReport, build_blueprint_run_report
from .bounded_dispatcher import BoundedDispatcher, DispatchConfig, DispatchRun
from .deep_orchestrate import DeepOrchestrate, TaskState
from .leaf_worker import DeterministicResearchWorker

GATE_VERSION = "oc-owner-authorization-gate-v1"


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Explicit per-task authorization decision from an identified owner.

    Fields
    ------
    task_key    The exact key of the OWNER_GATED task being decided.
    approved    True → authorize and release to READY. False → leave OWNER_GATED.
    approver_id Identity of the authorizing owner (e.g. "owner:president@fcosorchids.org").
    reason      Optional justification for the decision.
    """

    task_key: str
    approved: bool
    approver_id: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TaskAuthorizationOutcome:
    """Result of processing one AuthorizationDecision."""

    task_key: str
    approved: bool
    approver_id: str
    prior_state: str
    outcome_state: str  # state after gate applied decision
    error: str | None  # set if reservoir.authorize() raised unexpectedly
    processed_at: str  # ISO-8601 UTC


@dataclass(frozen=True, slots=True)
class OwnerAuthorizationResult:
    """Full result of one gate invocation.

    Fields
    ------
    authorized_count        Tasks approved and moved to READY.
    denied_count            Tasks with approved=False (left as OWNER_GATED).
    skipped_count           Decisions for tasks not in owner_gated_pending (ignored).
    error_count             Tasks where reservoir.authorize() raised unexpectedly.
    task_outcomes           Per-task outcome records.
    post_dispatch_run       DispatchRun from re-triggering BoundedDispatcher (None if
                            no tasks were authorized or dispatcher was not re-triggered).
    post_report             Updated BlueprintRunReport after dispatch (None if no
                            tasks were authorized).
    version                 Gate schema version.
    generated_at_utc        ISO-8601 UTC timestamp.
    """

    authorized_count: int
    denied_count: int
    skipped_count: int
    error_count: int
    task_outcomes: tuple[TaskAuthorizationOutcome, ...]
    post_dispatch_run: DispatchRun | None
    post_report: BlueprintRunReport | None
    version: str
    generated_at_utc: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "authorized_count": self.authorized_count,
            "denied_count": self.denied_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "task_outcomes": [
                {
                    "task_key": o.task_key,
                    "approved": o.approved,
                    "approver_id": o.approver_id,
                    "prior_state": o.prior_state,
                    "outcome_state": o.outcome_state,
                    "error": o.error,
                    "processed_at": o.processed_at,
                }
                for o in self.task_outcomes
            ],
            "post_dispatch_run": (
                self.post_dispatch_run.summary() if self.post_dispatch_run else None
            ),
            "post_report": (
                self.post_report.as_dict() if self.post_report else None
            ),
            "generated_at_utc": self.generated_at_utc,
        }


class OwnerAuthorizationGate:
    """Process explicit owner authorization decisions for OWNER_GATED tasks.

    Usage::

        gate = OwnerAuthorizationGate(reservoir, blueprint, worker=...)
        result = gate.authorize(
            report,
            decisions=[
                AuthorizationDecision(
                    task_key="research:abc123:canonical-mutation",
                    approved=True,
                    approver_id="owner:president@fcosorchids.org",
                    reason="Reviewed evidence; mutation is correct.",
                ),
            ],
            dispatch_config=DispatchConfig(max_tasks=10),
        )
        print(result.post_report.run_status)
    """

    def __init__(
        self,
        reservoir: DeepOrchestrate,
        blueprint: Any,  # ResearchBlueprint — avoid circular import
        worker: DeterministicResearchWorker | None = None,
    ) -> None:
        self.reservoir = reservoir
        self.blueprint = blueprint
        self.worker = worker or DeterministicResearchWorker()

    def authorize(
        self,
        report: BlueprintRunReport,
        decisions: list[AuthorizationDecision],
        *,
        dispatch_config: DispatchConfig | None = None,
    ) -> OwnerAuthorizationResult:
        """Process authorization decisions and re-trigger dispatch for approved tasks.

        Parameters
        ----------
        report      BlueprintRunReport with run_status "awaiting_owner_gate".
                    Tasks listed in report.owner_gated_pending are the only ones
                    eligible for authorization via this call.
        decisions   Explicit per-task authorization decisions. Unknown task keys
                    (not in owner_gated_pending) are skipped without error.
        dispatch_config  Config passed to BoundedDispatcher when re-triggering.
                    Defaults to DispatchConfig() if None.

        Returns
        -------
        OwnerAuthorizationResult with per-task outcomes, post-dispatch run, and
        an updated BlueprintRunReport.
        """
        eligible_keys: set[str] = {e["key"] for e in report.owner_gated_pending}

        outcomes: list[TaskAuthorizationOutcome] = []
        authorized_keys: list[str] = []
        denied_count = 0
        skipped_count = 0
        error_count = 0

        for decision in decisions:
            key = decision.task_key
            now_iso = datetime.now(timezone.utc).isoformat()

            if key not in eligible_keys:
                # Not an owner-gated task in this report — skip silently.
                skipped_count += 1
                live = self.reservoir.get(key)
                prior_state = live.state if live is not None else "unknown"
                outcomes.append(TaskAuthorizationOutcome(
                    task_key=key,
                    approved=decision.approved,
                    approver_id=decision.approver_id,
                    prior_state=prior_state,
                    outcome_state=prior_state,
                    error="SKIPPED:not_in_owner_gated_pending",
                    processed_at=now_iso,
                ))
                continue

            live = self.reservoir.get(key)
            prior_state = live.state if live is not None else "unknown"

            if not decision.approved:
                # Denied — leave OWNER_GATED, no mutation.
                denied_count += 1
                outcomes.append(TaskAuthorizationOutcome(
                    task_key=key,
                    approved=False,
                    approver_id=decision.approver_id,
                    prior_state=prior_state,
                    outcome_state=prior_state,
                    error=None,
                    processed_at=now_iso,
                ))
                continue

            # Approved — call the canonical authorization path.
            if prior_state in (TaskState.COMPLETED, TaskState.READY):
                # Already completed or ready (idempotent re-approval) — no-op.
                authorized_keys.append(key)
                outcomes.append(TaskAuthorizationOutcome(
                    task_key=key,
                    approved=True,
                    approver_id=decision.approver_id,
                    prior_state=prior_state,
                    outcome_state=prior_state,
                    error=None,
                    processed_at=now_iso,
                ))
                continue

            try:
                released = self.reservoir.authorize(key)
                outcome_state = released.state
                authorized_keys.append(key)
                error_val = None
            except (LookupError, ValueError) as exc:
                error_count += 1
                outcome_state = prior_state
                error_val = str(exc)

            outcomes.append(TaskAuthorizationOutcome(
                task_key=key,
                approved=True,
                approver_id=decision.approver_id,
                prior_state=prior_state,
                outcome_state=outcome_state,
                error=error_val,
                processed_at=now_iso,
            ))

        # Re-trigger dispatcher only when at least one task was authorized.
        post_run: DispatchRun | None = None
        post_report: BlueprintRunReport | None = None
        if authorized_keys:
            cfg = dispatch_config or DispatchConfig()
            dispatcher = BoundedDispatcher(self.reservoir, worker=self.worker)
            post_run = dispatcher.run(config=cfg)
            post_report = build_blueprint_run_report(self.blueprint, post_run, self.reservoir)

        return OwnerAuthorizationResult(
            authorized_count=len(authorized_keys),
            denied_count=denied_count,
            skipped_count=skipped_count,
            error_count=error_count,
            task_outcomes=tuple(outcomes),
            post_dispatch_run=post_run,
            post_report=post_report,
            version=GATE_VERSION,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
        )
