"""Blueprint execution report: aggregate DispatchRun results → typed run summary.

This is the next link after BoundedDispatcher.run() in the autonomous research loop:

    BoundedDispatcher.run() → DispatchRun
    → build_blueprint_run_report(blueprint, run, reservoir)
    → BlueprintRunReport

BlueprintRunReport answers four questions:
  1. Which tasks completed and what evidence did they produce?
  2. Which tasks are still OWNER_GATED and need explicit human authorization?
  3. Which tasks are BLOCKED or in REPAIR_BACKOFF (will retry)?
  4. What is the overall run status?

Run status values (priority order):
  "all_complete"       — every leaf in the blueprint is COMPLETED
  "awaiting_owner_gate"— all non-owner-gated leaves COMPLETED; ≥1 OWNER_GATED remains
  "partially_blocked"  — ≥1 leaf is BLOCKED/REPAIR_BACKOFF; no leaf is in_progress/ready
  "in_progress"        — ≥1 leaf is READY, LEASED, RUNNING, or VALIDATING

This report is provider-free: it reads from the live reservoir and the DispatchRun
accumulator only; it never calls any external API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .bounded_dispatcher import DispatchRun
from .deep_orchestrate import (
    _ACTIVE,
    DeepOrchestrate,
    TaskLeaf,
    TaskState,
)
from .leaf_worker import TaskExecutionResult

# These states mean the leaf still has work ahead of it (active or will become ready).
_IN_PROGRESS_STATES = frozenset({
    TaskState.READY,
    TaskState.LEASED,
    TaskState.RUNNING,
    TaskState.VALIDATING,
    TaskState.REPAIR_BACKOFF,
})

REPORT_VERSION = "oc-blueprint-run-report-v1"


@dataclass(frozen=True, slots=True)
class BlueprintRunReport:
    """Typed, immutable summary of one bounded dispatch run against a blueprint.

    Fields
    ------
    blueprint_id        SHA-256 fingerprint of the source ResearchBlueprint
    run_fingerprint     SHA-256 fingerprint from the source RunEvidenceManifest
    proposed_action     The governed action that was admitted
    human_review_required  Carried from blueprint governance flags
    run_status          "all_complete" | "awaiting_owner_gate" |
                        "partially_blocked" | "in_progress"
    total_leaves        Total task leaves declared in the blueprint
    completed           Completed leaves with their execution evidence
    blocked             BLOCKED leaves with reason
    repair_backoff      REPAIR_BACKOFF leaves (expired leases awaiting retry)
    owner_gated_pending OWNER_GATED leaves awaiting human authorization
    active              Leaves currently leased/running/validating
    ready               Leaves currently READY (not yet leased)
    dispatch_summary    Raw DispatchRun.summary() dict
    generated_at_utc    ISO-8601 UTC timestamp when this report was built
    version             Report schema version
    """

    blueprint_id: str
    run_fingerprint: str
    proposed_action: str
    human_review_required: bool
    run_status: str
    total_leaves: int
    completed: tuple[dict[str, Any], ...]
    blocked: tuple[dict[str, Any], ...]
    repair_backoff: tuple[dict[str, Any], ...]
    owner_gated_pending: tuple[dict[str, Any], ...]
    active: tuple[dict[str, Any], ...]
    ready: tuple[dict[str, Any], ...]
    dispatch_summary: dict[str, Any]
    generated_at_utc: str
    version: str = field(default=REPORT_VERSION)

    def as_dict(self) -> dict[str, Any]:
        """Fully serializable dict for routes, logging, and downstream consumers."""
        return {
            "version": self.version,
            "blueprint_id": self.blueprint_id,
            "run_fingerprint": self.run_fingerprint,
            "proposed_action": self.proposed_action,
            "human_review_required": self.human_review_required,
            "run_status": self.run_status,
            "total_leaves": self.total_leaves,
            "counts": {
                "completed": len(self.completed),
                "blocked": len(self.blocked),
                "repair_backoff": len(self.repair_backoff),
                "owner_gated_pending": len(self.owner_gated_pending),
                "active": len(self.active),
                "ready": len(self.ready),
            },
            "completed": list(self.completed),
            "blocked": list(self.blocked),
            "repair_backoff": list(self.repair_backoff),
            "owner_gated_pending": list(self.owner_gated_pending),
            "active": list(self.active),
            "ready": list(self.ready),
            "dispatch_summary": self.dispatch_summary,
            "generated_at_utc": self.generated_at_utc,
        }


def build_blueprint_run_report(
    blueprint: Any,  # ResearchBlueprint — avoid circular import
    run: DispatchRun,
    reservoir: DeepOrchestrate,
) -> BlueprintRunReport:
    """Aggregate a completed DispatchRun against a blueprint into a typed report.

    Parameters
    ----------
    blueprint   The ResearchBlueprint whose task_leaves were dispatched.
    run         The DispatchRun returned by BoundedDispatcher.run().
    reservoir   The same DeepOrchestrate instance used for dispatch (for live state).

    Returns
    -------
    BlueprintRunReport with run_status, classified task lists, and dispatch_summary.

    Never raises; missing tasks (not registered in reservoir) are classified as
    "unknown" and counted toward in_progress to conservatively avoid false "all_complete".
    """
    # Index execution results by task_key for O(1) lookup.
    result_by_key: dict[str, TaskExecutionResult] = {
        r.task_key: r for r in run.results
    }

    completed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    repair_backoff: list[dict[str, Any]] = []
    owner_gated: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    ready: list[dict[str, Any]] = []

    for leaf in blueprint.task_leaves:
        live: TaskLeaf | None = reservoir.get(leaf.key)
        state = live.state if live is not None else "unknown"
        entry = _leaf_entry(leaf, state, result_by_key.get(leaf.key))

        if state == TaskState.COMPLETED:
            completed.append(entry)
        elif state == TaskState.BLOCKED:
            blocked.append(entry)
        elif state == TaskState.REPAIR_BACKOFF:
            repair_backoff.append(entry)
        elif state == TaskState.OWNER_GATED:
            owner_gated.append(entry)
        elif state in _ACTIVE:
            active.append(entry)
        else:
            # READY, "unknown", or any future state → counts as in_progress.
            ready.append(entry)

    run_status = _compute_run_status(
        total=len(blueprint.task_leaves),
        completed_count=len(completed),
        owner_gated_count=len(owner_gated),
        blocked_count=len(blocked),
        # REPAIR_BACKOFF tasks will be retried → still in progress.
        in_progress_count=len(active) + len(ready) + len(repair_backoff),
    )

    return BlueprintRunReport(
        blueprint_id=blueprint.blueprint_id,
        run_fingerprint=blueprint.run_fingerprint,
        proposed_action=blueprint.proposed_action,
        human_review_required=blueprint.human_review_required,
        run_status=run_status,
        total_leaves=len(blueprint.task_leaves),
        completed=tuple(completed),
        blocked=tuple(blocked),
        repair_backoff=tuple(repair_backoff),
        owner_gated_pending=tuple(owner_gated),
        active=tuple(active),
        ready=tuple(ready),
        dispatch_summary=run.summary(),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        version=REPORT_VERSION,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _leaf_entry(
    leaf: TaskLeaf,
    state: str,
    result: TaskExecutionResult | None,
) -> dict[str, Any]:
    """Build a serializable entry for one leaf in the report."""
    entry: dict[str, Any] = {
        "key": leaf.key,
        "title": leaf.title,
        "authority_class": leaf.authority_class,
        "priority": leaf.priority,
        "state": state,
        "requires_owner_gate": leaf.requires_owner_gate,
    }
    if result is not None:
        entry["execution_result"] = result.as_evidence()
    if state == TaskState.BLOCKED and result is not None:
        entry["blocked_reason"] = result.error_reason
    return entry


def _compute_run_status(
    total: int,
    completed_count: int,
    owner_gated_count: int,
    blocked_count: int,
    in_progress_count: int,
) -> str:
    """Classify the overall run status from leaf state counts.

    Priority order:
      1. all_complete        — every leaf is COMPLETED
      2. in_progress         — any leaf is READY/ACTIVE/REPAIR_BACKOFF
      3. awaiting_owner_gate — all non-gated complete; only OWNER_GATED remain
      4. partially_blocked   — some BLOCKED; nothing left running/ready
    """
    if total == 0 or completed_count == total:
        return "all_complete"
    if in_progress_count > 0:
        return "in_progress"
    if completed_count + owner_gated_count == total:
        return "awaiting_owner_gate"
    return "partially_blocked"
