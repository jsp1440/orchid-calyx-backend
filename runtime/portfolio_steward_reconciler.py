"""Portfolio Steward reconciler — operational autonomous reconciliation/refill path.

Connects the Portfolio Steward control plane (GitHub oc-prepared issues) to the
durable orchestration pipeline without paid providers or new schedulers.

Cycle (one reconciliation pass):
    1. Filter input issue dicts to those labelled oc-prepared (not blocked/done)
    2. Map each to a TaskLeaf: key "issue-{number}:retrieve-evidence"
    3. Register leaves in a DeepOrchestrate planner
    4. Run plan_deep_orchestrate_refill against the caller-supplied snapshot
       (fingerprint/semantic deduplication happens inside the bridge)
    5. For each admitted proposal: register a DurableOrchestrate task
    6. Execute via BoundedDispatcher + DeterministicResearchWorker
    7. Return a PortfolioStewardReport with all evidence

Invariants (mirrors Provider Governor #535 policies):
    - AUTH_PRODUCTION leaves → OWNER_GATED; never enter reserve
    - Leaves with no issue_number → rejected as missing_issue_lineage
    - Unchanged fingerprint in snapshot → zero new proposals (dedup)
    - provider_launch_authorized: False throughout
    - no_api_mode: True throughout
    - No paid API calls ever made

This module is side-effect-free with respect to GitHub state.  Callers
that want to persist label changes (oc-prepared → oc-queued) must do so
separately using the audited dispatcher in runtime/github_connector_dispatcher.py.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.calyx_orchestrator.bounded_dispatcher import BoundedDispatcher, DispatchConfig
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
)
from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
from app.calyx_orchestrator.durable_reservoir_models import (
    DurableReservoirRun,
    DurableReservoirTask,
)
from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker
from app.database import Base
from runtime.deep_orchestrate_queue_bridge import plan_deep_orchestrate_refill
from scripts.oc_portfolio_scheduler import label_names

_SCHEMA = "oc.portfolio-steward-reconciler.v1"
_CONTEXT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "oc-autonomy-context.v1.json"


def _load_canonical_context() -> dict[str, Any]:
    """Load and minimally validate the provider-neutral autonomy context.

    This fails closed: a missing, malformed, or wrong-schema contract prevents
    autonomous reconciliation rather than silently running without its rules.
    """
    with _CONTEXT_PATH.open(encoding="utf-8") as fh:
        context = json.load(fh)
    if context.get("schema") != "oc.autonomy-context.v1":
        raise RuntimeError("invalid canonical autonomy context schema")
    if not context.get("provider_neutral"):
        raise RuntimeError("canonical autonomy context must be provider-neutral")
    if not context.get("operating_rules", {}).get("require_evidence_for_completion"):
        raise RuntimeError("canonical autonomy context must require completion evidence")
    return context


# Labels that disqualify an issue from the oc-prepared pool.
_BLOCKING_LABELS = frozenset({"oc-done", "oc-blocked", "oc-owner-gate", "oc-running",
                               "oc-queued", "oc-validating", "oc-runtime-backoff",
                               "oc-repair-backoff"})

# Priority label → Priority enum
_PRIORITY_MAP: dict[str, Priority] = {
    "oc-p0": Priority.P0,
    "oc-p1": Priority.P1,
    "oc-p2": Priority.P2,
    "oc-p3": Priority.P3,
    "oc-p4": Priority.P4,
}
_DEFAULT_PRIORITY = Priority.P2


@dataclass(frozen=True, slots=True)
class PortfolioStewardReport:
    """Result of one reconciliation pass.

    Fields
    ------
    run_id              Unique identifier for this reconciliation pass.
    schema              Proof schema version.
    source_count        Number of oc-prepared issues supplied.
    admitted_count      Proposals admitted to the durable pipeline.
    executed_count      Tasks that reached COMPLETED terminal state.
    blocked_count       Tasks that ended in BLOCKED state.
    rejected_count      Source-level rejections (missing lineage, etc.).
    dedup_suppressed    Proposals suppressed by fingerprint/semantic dedup.
    bridge_result       Raw output of plan_deep_orchestrate_refill.
    evidence            Evidence records from completed task leaves.
    provider_launch_authorized  Always False.
    no_api_mode         Always True.
    generated_at_utc    ISO-8601 UTC timestamp.
    """

    run_id: str
    schema: str
    source_count: int
    admitted_count: int
    executed_count: int
    blocked_count: int
    rejected_count: int
    dedup_suppressed: int
    bridge_result: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    provider_launch_authorized: bool
    no_api_mode: bool
    generated_at_utc: str
    canonical_context_schema: str
    canonical_context_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "source_count": self.source_count,
            "admitted_count": self.admitted_count,
            "executed_count": self.executed_count,
            "blocked_count": self.blocked_count,
            "rejected_count": self.rejected_count,
            "dedup_suppressed": self.dedup_suppressed,
            "bridge_result": self.bridge_result,
            "evidence": list(self.evidence),
            "provider_launch_authorized": self.provider_launch_authorized,
            "no_api_mode": self.no_api_mode,
            "generated_at_utc": self.generated_at_utc,
            "canonical_context_schema": self.canonical_context_schema,
            "canonical_context_version": self.canonical_context_version,
        }


def _priority_from_labels(labels: list[str]) -> Priority:
    for label in labels:
        if label in _PRIORITY_MAP:
            return _PRIORITY_MAP[label]
    return _DEFAULT_PRIORITY


def _issue_to_leaf(issue: dict[str, Any]) -> TaskLeaf | None:
    """Map a GitHub issue dict to a TaskLeaf. Returns None for invalid issues."""
    number = issue.get("number")
    if not isinstance(number, int) or number <= 0:
        return None
    title = str(issue.get("title") or "").strip() or f"Frontend issue #{number}"
    labels = label_names(issue)
    priority = _priority_from_labels(labels)
    return TaskLeaf(
        key=f"issue-{number}:retrieve-evidence",
        title=title,
        repo="orchid-continuum-frontend",
        module="features/queue-bridge",
        priority=priority,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
        issue_number=number,
        acceptance_criteria=[f"retrieve-evidence for frontend issue #{number} completes provider-free"],
    )


def _filter_prepared(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return issues that are in the oc-prepared pool (eligible for first admission)."""
    eligible = []
    for issue in issues:
        labels = set(label_names(issue))
        if "oc-prepared" not in labels:
            continue
        if labels & _BLOCKING_LABELS:
            continue
        eligible.append(issue)
    return eligible


def reconcile(
    issues: list[dict[str, Any]],
    snapshot: dict[str, Any],
    *,
    run_id: str | None = None,
    reserve_depth: int = 2,
    max_tasks: int = 10,
    max_iterations: int = 5,
    db_url: str = "sqlite:///:memory:",
) -> PortfolioStewardReport:
    """Execute one Portfolio Steward reconciliation pass.

    Parameters
    ----------
    issues:
        List of GitHub issue dicts (same format as oc_portfolio_scheduler uses).
        Typically the full oc-prepared pool from the frontend repo.
    snapshot:
        Current reservation snapshot: ``{"issues": [...], "leases": [...],
        "dispatch_fingerprints": [...]}``.  Used for fingerprint and semantic
        deduplication by plan_deep_orchestrate_refill.
    run_id:
        Optional caller-supplied run identifier. Auto-generated if None.
    reserve_depth:
        Maximum new proposals admitted in this cycle.
    max_tasks:
        BoundedDispatcher task cap per cycle.
    max_iterations:
        BoundedDispatcher iteration cap per cycle.
    db_url:
        SQLAlchemy URL for DurableOrchestrate.  Defaults to in-memory SQLite
        (suitable for unit tests).  Production callers pass a PostgreSQL URL
        via the DATABASE_URL environment variable.

    Returns
    -------
    PortfolioStewardReport
        Complete evidence of this reconciliation pass.
    """
    run_id = run_id or f"psr-{uuid.uuid4().hex[:12]}"
    canonical_context = _load_canonical_context()

    # 1. Filter to oc-prepared eligible items
    prepared = _filter_prepared(issues)

    # 2. Build DeepOrchestrate planner from eligible leaves
    planner = DeepOrchestrate(configured_width=max(reserve_depth * 2, 4))
    valid_leaves: list[TaskLeaf] = []
    for issue in prepared:
        leaf = _issue_to_leaf(issue)
        if leaf is not None:
            planner.register(leaf)
            valid_leaves.append(leaf)

    # 3. Run the Queue Bridge (fingerprint/semantic dedup against snapshot)
    bridge = plan_deep_orchestrate_refill(planner, snapshot, reserve_depth=reserve_depth)

    admitted_proposals = bridge.get("proposals", [])
    source_rejections = bridge.get("source_rejections", [])
    dedup_suppressed = len(valid_leaves) - len(admitted_proposals) - len(source_rejections)

    # 4. Provision DurableOrchestrate and execute admitted proposals
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
        poolclass=StaticPool if "sqlite" in db_url else None,
    )
    # Provision only the reservoir tables this pass uses. ``Base.metadata`` is the
    # application-wide registry and also carries schema-qualified tables
    # (``research_station.*``, ``reasoning_ledger.*``) whenever ``app.main`` has been
    # imported in the same process; SQLite cannot create those ("unknown database
    # research_station"), and a production PostgreSQL URL must not have unrelated
    # ORM tables created as a side effect of a steward pass.
    Base.metadata.create_all(
        engine, tables=[DurableReservoirRun.__table__, DurableReservoirTask.__table__]
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    try:
        reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=max_tasks)

        # Register only admitted tasks (leaves whose proposals passed dedup)
        admitted_keys = {p["semantic_key"].removeprefix("deep-orchestrate:") for p in admitted_proposals}
        for leaf in valid_leaves:
            if leaf.key in admitted_keys:
                reservoir.register(leaf)

        # 5. Execute via BoundedDispatcher + DeterministicResearchWorker
        worker = DeterministicResearchWorker()
        BoundedDispatcher(reservoir, worker=worker).run(
            DispatchConfig(max_tasks=max_tasks, max_iterations=max_iterations)
        )

        # 6. Collect evidence and terminal-state counts
        all_tasks = reservoir.to_dict().get("tasks", {})
        executed_count = sum(1 for t in all_tasks.values() if t.get("state") == "completed")
        blocked_count = sum(1 for t in all_tasks.values() if t.get("state") == "blocked")
        evidence = tuple(
            {
                "issue_number": t.get("issue_number"),
                "task_key": key,
                "state": t.get("state"),
                "evidence": t.get("evidence"),
                "provider_api_called": (t.get("evidence") or {}).get("output", {}).get("provider_api_called", False),
            }
            for key, t in all_tasks.items()
        )

    finally:
        session.close()
        engine.dispose()

    return PortfolioStewardReport(
        run_id=run_id,
        schema=_SCHEMA,
        source_count=len(prepared),
        admitted_count=len(admitted_proposals),
        executed_count=executed_count,
        blocked_count=blocked_count,
        rejected_count=len(source_rejections),
        dedup_suppressed=max(0, dedup_suppressed),
        bridge_result=bridge,
        evidence=evidence,
        provider_launch_authorized=False,
        no_api_mode=True,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        canonical_context_schema=canonical_context["schema"],
        canonical_context_version=canonical_context["version"],
    )
