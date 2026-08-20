"""AUDIT-FOLLOWTHROUGH-001 (TWO-DAY-SLICE-A / issue #1025).

Audits that only narrate a problem and never create durable remediation work
are not "complete". This module is the single place that:

- defines the finding-disposition model every actionable audit finding must
  resolve to;
- derives a deterministic dedupe key from the originating audit + finding
  identity so repeat audit runs never create duplicate remediation tasks;
- converts actionable findings into ``oc_admin.calyx_tasks``-shaped payloads
  while preserving the originating audit id, evidence, and provenance;
- enforces that an audit result cannot claim completion for an actionable
  finding unless that finding carries a terminal disposition or has queued
  remediation;
- persists the queued remediation into ``oc_admin.calyx_tasks`` idempotently,
  keyed on the deterministic dedupe key, so repeat audit runs converge on the
  same durable task instead of accumulating duplicates.

High-risk task types are routed through the existing
``DefaultTaskExecutor.risky_action`` owner-gate in
``runtime.autonomous_orchestrator`` rather than a second, parallel notion of
"risky" defined here. Nothing in this module approves, merges, deploys, or
publishes anything: owner-gated tasks are written as ``needs_review`` and stay
there until the existing approval path is used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from runtime.autonomous_orchestrator import DefaultTaskExecutor

# The seven terminal dispositions every actionable finding must resolve to,
# exactly as specified for TWO-DAY-SLICE-A. Order is significant only for
# readability; membership is what is enforced.
FINDING_DISPOSITIONS = (
    "auto_remediation_queued",
    "in_progress",
    "verified_resolved",
    "owner_approval_required",
    "external_blocker",
    "scientific_data_gap",
    "no_action_needed",
)
TERMINAL_FINDING_DISPOSITIONS = frozenset(FINDING_DISPOSITIONS)

# Dispositions that represent a finding never becoming a code/task remediation
# because the finding itself is not something a task can resolve.
NON_ACTIONABLE_DISPOSITIONS = frozenset(
    {"external_blocker", "scientific_data_gap", "no_action_needed"}
)

# Dispositions that mean "follow-through is still owed": the finding is only
# accounted for because durable remediation exists (or is owner-gated). An
# audit carrying any of these is not "fully complete" -- it is
# ``follow_through_pending``.
OPEN_DISPOSITIONS = frozenset(
    {"auto_remediation_queued", "in_progress", "owner_approval_required"}
)

# Dispositions that close a finding out without further remediation work.
# ``external_blocker`` and ``scientific_data_gap`` are closed *for this
# repository's automation*, not "solved": they are deliberately kept distinct
# from ``verified_resolved`` so an unavailable measurement is never reported as
# a resolved one.
RESOLVED_DISPOSITIONS = frozenset(
    {"verified_resolved", "external_blocker", "scientific_data_gap", "no_action_needed"}
)

DEFAULT_TASK_TYPE = "audit_followthrough_remediation"

# Statuses the orchestrator's own CHECK constraint allows on
# ``oc_admin.calyx_tasks``. Follow-through only ever writes the two entry
# statuses; it never writes a terminal status and never approves.
_WRITABLE_TASK_STATUSES = frozenset({"pending", "needs_review"})


class InvalidDispositionError(ValueError):
    """Raised when a disposition outside the seven terminal states is used."""


class NarrativeOnlyCompletionError(RuntimeError):
    """Raised when an audit is reported complete without follow-through.

    This is the structural guard against "audit ran, findings were listed,
    nothing durable happened" reporting: it fires whenever an actionable
    finding has no disposition at all.
    """


def validate_disposition(disposition: str) -> str:
    """Normalize and validate a disposition string, failing closed."""

    normalized = str(disposition).strip().lower()
    if normalized not in TERMINAL_FINDING_DISPOSITIONS:
        raise InvalidDispositionError(
            f"unsupported finding disposition: {disposition!r}; "
            f"must be one of {sorted(TERMINAL_FINDING_DISPOSITIONS)}"
        )
    return normalized


def dedupe_key(audit_source: str, finding_key: str) -> str:
    """Stable id for a finding across repeat runs of the same audit.

    Deliberately keyed on ``audit_source`` (the audit's stable identity, e.g.
    an audit type or slug) rather than a per-run audit id, so the same
    finding recurring across successive runs of the same audit maps to the
    same dedupe key and therefore the same task -- that is what makes
    duplicate suppression possible.
    """

    raw = f"{str(audit_source).strip().lower()}::{str(finding_key).strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def task_key_for_finding(audit_source: str, finding_key: str) -> str:
    return f"audit-followthrough:{dedupe_key(audit_source, finding_key)}"


@dataclass(frozen=True)
class ActionableFinding:
    """One finding from any audit, prepared for follow-through classification."""

    finding_key: str
    title: str
    audit_source: str
    audit_id: str
    evidence: dict[str, Any]
    actionable: bool = True
    non_actionable_reason: Optional[str] = None
    task_type: str = DEFAULT_TASK_TYPE
    priority: int = 50

    def __post_init__(self) -> None:
        if not self.actionable and self.non_actionable_reason is not None:
            validate_disposition(self.non_actionable_reason)
            if self.non_actionable_reason not in NON_ACTIONABLE_DISPOSITIONS:
                raise InvalidDispositionError(
                    f"non_actionable_reason must be one of "
                    f"{sorted(NON_ACTIONABLE_DISPOSITIONS)}, got "
                    f"{self.non_actionable_reason!r}"
                )


@dataclass(frozen=True)
class FindingRemediation:
    """The outcome of classifying one finding: its disposition and any task.

    ``task`` is the payload for a task that still has to be created.
    ``task_key`` is the durable dedupe key of the task that accounts for this
    finding, whether that task is being created now or already exists. An open
    disposition without a ``task_key`` is exactly the narrative-only failure
    mode this module exists to prevent, so :func:`enforce_followthrough`
    rejects it.
    """

    finding_key: str
    disposition: str
    task: Optional[dict[str, Any]] = None
    rationale: str = ""
    task_key: Optional[str] = None

    def __post_init__(self) -> None:
        validate_disposition(self.disposition)

    @property
    def effective_task_key(self) -> Optional[str]:
        return self.task_key or (self.task or {}).get("task_key")


def _task_payload(finding: ActionableFinding) -> dict[str, Any]:
    return {
        "audit_id": finding.audit_id,
        "audit_source": finding.audit_source,
        "finding_key": finding.finding_key,
        "evidence": finding.evidence,
        "execution_mode": "draft_only",
        "automatic_merge": False,
        "automatic_deploy": False,
        "automatic_publication": False,
    }


def build_remediation(
    finding: ActionableFinding,
    *,
    executor: Optional[DefaultTaskExecutor] = None,
) -> FindingRemediation:
    """Classify a single finding with no knowledge of any prior task state."""

    if not finding.actionable:
        disposition = finding.non_actionable_reason or "no_action_needed"
        return FindingRemediation(
            finding_key=finding.finding_key,
            disposition=validate_disposition(disposition),
            task=None,
            rationale="finding marked non-actionable at the source",
        )

    executor = executor or DefaultTaskExecutor()
    payload = _task_payload(finding)
    risky = executor.risky_action(finding.task_type, payload)
    task = {
        "task_key": task_key_for_finding(finding.audit_source, finding.finding_key),
        "task_type": finding.task_type,
        "title": finding.title,
        "priority": finding.priority,
        "required_approval": bool(risky),
        "status": "needs_review" if risky else "pending",
        "payload": payload,
    }
    disposition = "owner_approval_required" if risky else "auto_remediation_queued"
    rationale = (
        f"task type routes through the existing owner-gate ({risky})"
        if risky
        else "safe/reversible finding queued for autonomous remediation"
    )
    return FindingRemediation(
        finding_key=finding.finding_key,
        disposition=disposition,
        task=task,
        rationale=rationale,
        task_key=task["task_key"],
    )


def plan_remediation(
    findings: Iterable[ActionableFinding],
    *,
    executor: Optional[DefaultTaskExecutor] = None,
    existing_tasks_by_key: Optional[dict[str, dict[str, Any]]] = None,
) -> list[FindingRemediation]:
    """Classify a batch of findings, deduping against in-flight/prior tasks.

    ``existing_tasks_by_key`` maps ``task_key`` (as produced by
    :func:`task_key_for_finding`) to the current ``oc_admin.calyx_tasks`` row
    for that key, if one already exists. A finding whose task is already
    pending/needs_review/running is reported as ``in_progress`` (or
    ``owner_approval_required`` if it is still waiting on the owner gate)
    instead of creating a second, duplicate task. A finding whose prior task
    completed and passed evaluation is reported ``verified_resolved``. A
    finding whose prior task failed or was blocked is requeued under the same
    dedupe key rather than left unresolved.
    """

    executor = executor or DefaultTaskExecutor()
    existing_tasks_by_key = existing_tasks_by_key or {}
    plans: list[FindingRemediation] = []
    seen_keys: set[str] = set()

    for finding in findings:
        if not finding.actionable:
            plans.append(build_remediation(finding, executor=executor))
            continue

        key = task_key_for_finding(finding.audit_source, finding.finding_key)
        if key in seen_keys:
            # Same finding surfaced twice in one audit batch; do not queue it twice.
            plans.append(
                FindingRemediation(
                    finding_key=finding.finding_key,
                    disposition="in_progress",
                    task=None,
                    rationale=f"duplicate of an already-planned finding in this batch ({key})",
                    task_key=key,
                )
            )
            continue
        seen_keys.add(key)

        existing = existing_tasks_by_key.get(key)
        if existing is None:
            plans.append(build_remediation(finding, executor=executor))
            continue

        status = str(existing.get("status", "")).lower()
        if status == "completed" and existing.get("evaluation_result") == "pass":
            plans.append(
                FindingRemediation(
                    finding_key=finding.finding_key,
                    disposition="verified_resolved",
                    task=None,
                    rationale=f"existing task {key} completed and verified",
                    task_key=key,
                )
            )
        elif status in {"pending", "running"}:
            plans.append(
                FindingRemediation(
                    finding_key=finding.finding_key,
                    disposition="in_progress",
                    task=None,
                    rationale=f"existing task {key} already {status}; not duplicating",
                    task_key=key,
                )
            )
        elif status == "needs_review":
            plans.append(
                FindingRemediation(
                    finding_key=finding.finding_key,
                    disposition="owner_approval_required",
                    task=None,
                    rationale=f"existing task {key} is waiting on the owner-approval gate",
                    task_key=key,
                )
            )
        else:
            # failed / blocked / unknown: requeue under the same dedupe key
            # rather than silently reporting the finding as handled.
            plans.append(build_remediation(finding, executor=executor))

    return plans


def enforce_followthrough(
    findings: Iterable[ActionableFinding],
    remediations: Iterable[FindingRemediation],
) -> None:
    """Fail closed on any finding that is narrated but not actually accounted for.

    Two structural failure modes are rejected here:

    1. a finding was dropped -- listed in a report but never classified at all;
    2. a finding carries an *open* disposition (``auto_remediation_queued`` /
       ``in_progress`` / ``owner_approval_required``) with no durable task key
       behind it, i.e. the audit says remediation is under way while nothing
       durable exists to make that true.

    A disposition value outside the seven terminal states is already
    impossible by construction (``FindingRemediation.__post_init__``
    validates it). Together these close off the "narrative-only completion"
    failure mode #1025 exists to prevent.
    """

    remediations = list(remediations)
    remediated_keys = {remediation.finding_key for remediation in remediations}
    missing = [
        finding.finding_key for finding in findings if finding.finding_key not in remediated_keys
    ]
    if missing:
        raise NarrativeOnlyCompletionError(
            "audit cannot be reported complete: actionable findings without a "
            f"disposition: {sorted(missing)}"
        )

    unbacked = [
        remediation.finding_key
        for remediation in remediations
        if remediation.disposition in OPEN_DISPOSITIONS and not remediation.effective_task_key
    ]
    if unbacked:
        raise NarrativeOnlyCompletionError(
            "audit cannot claim in-flight remediation without a durable task "
            f"for findings: {sorted(unbacked)}"
        )


def audit_completion_state(remediations: Iterable[FindingRemediation]) -> dict[str, Any]:
    """Whether the audit is fully complete or still owes follow-through.

    An audit is ``complete`` only when every finding sits in a resolved
    disposition. Any finding still queued, in progress, or waiting on the
    owner gate makes the audit ``follow_through_pending`` -- explicitly not
    "complete", no matter how thorough the narrative is.
    """

    remediations = list(remediations)
    counts: dict[str, int] = {}
    for remediation in remediations:
        counts[remediation.disposition] = counts.get(remediation.disposition, 0) + 1
    open_findings = sorted(
        remediation.finding_key
        for remediation in remediations
        if remediation.disposition in OPEN_DISPOSITIONS
    )
    return {
        "state": "follow_through_pending" if open_findings else "complete",
        "open_findings": open_findings,
        "disposition_counts": counts,
        "findings_total": len(remediations),
    }


def next_actions_created(remediations: Iterable[FindingRemediation]) -> list[dict[str, Any]]:
    """The owner-facing summary shape: what follow-through actually happened."""

    return [
        {
            "finding_key": remediation.finding_key,
            "disposition": remediation.disposition,
            "task_key": remediation.effective_task_key,
            "required_approval": bool((remediation.task or {}).get("required_approval")),
            "task_created": remediation.task is not None,
            "rationale": remediation.rationale,
        }
        for remediation in remediations
    ]


def run_followthrough(
    findings: Iterable[ActionableFinding],
    *,
    executor: Optional[DefaultTaskExecutor] = None,
    existing_tasks_by_key: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Classify findings, enforce completeness, and return the summary shape.

    This is the one function repository-local audit code paths should call:
    it plans remediation, refuses to return anything if narrative-only
    completion is detected, and returns the ``next_actions_created`` summary
    plus the durable task payloads ready for
    ``CalyxAutonomousOrchestrator.create_task``.
    """

    findings = list(findings)
    remediations = plan_remediation(
        findings, executor=executor, existing_tasks_by_key=existing_tasks_by_key
    )
    enforce_followthrough(findings, remediations)
    tasks = [remediation.task for remediation in remediations if remediation.task is not None]
    return {
        "next_actions_created": next_actions_created(remediations),
        "tasks_to_create": tasks,
        "completion_state": audit_completion_state(remediations),
    }


# ---------------------------------------------------------------------------
# Durable persistence into oc_admin.calyx_tasks
# ---------------------------------------------------------------------------


class FollowthroughPersistenceError(RuntimeError):
    """Raised when a planned task cannot be written durably."""


class OrchestratorFollowthroughStore:
    """Reads/writes follow-through tasks in ``oc_admin.calyx_tasks``.

    Wraps an existing :class:`~runtime.autonomous_orchestrator.CalyxAutonomousOrchestrator`
    so follow-through reuses that module's connection handling, schema
    creation, and observation log rather than opening a second, divergent
    persistence path.

    Writes are bounded and idempotent: every insert is keyed on the
    deterministic ``task_key`` and uses ``ON CONFLICT (task_key) DO NOTHING``,
    so re-running the same audit converges on the same row instead of
    accumulating duplicates. Only ``pending``/``needs_review`` may be written;
    this store never approves a task, never sets ``approved_at``, and never
    touches scientific tables.
    """

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    def fetch_tasks_by_key(self, task_keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        keys = list(dict.fromkeys(key for key in task_keys if key))
        if not keys:
            return {}
        with self.orchestrator.connect() as conn:
            with conn.cursor() as cur:
                self.orchestrator.ensure_schema(cur)
                cur.execute(
                    """
                    SELECT id, task_key, task_type, status, required_approval,
                           evaluation_result, payload
                    FROM oc_admin.calyx_tasks
                    WHERE task_key = ANY(%s)
                    """,
                    (keys,),
                )
                rows = [dict(row) for row in cur.fetchall()]
            conn.commit()
        return {row["task_key"]: row for row in rows if row.get("task_key")}

    def insert_task(self, task: dict[str, Any]) -> dict[str, Any]:
        status = str(task.get("status", "pending")).lower()
        if status not in _WRITABLE_TASK_STATUSES:
            raise FollowthroughPersistenceError(
                f"audit follow-through may only write {sorted(_WRITABLE_TASK_STATUSES)}, "
                f"got {status!r}"
            )
        task_key = task.get("task_key")
        if not task_key:
            raise FollowthroughPersistenceError("follow-through task is missing its dedupe key")

        from runtime.autonomous_orchestrator import _json  # local: needs psycopg

        payload = task.get("payload") or {}
        with self.orchestrator.connect() as conn:
            with conn.cursor() as cur:
                self.orchestrator.ensure_schema(cur)
                # The DO UPDATE arm is deliberately guarded to dead rows only:
                # a task that failed or was blocked is revived under the same
                # dedupe key (otherwise the finding is "handled" by a row that
                # will never run again), while pending/running/needs_review/
                # completed rows are left exactly as they are. Nothing here
                # clears approved_at, so a revived risky task is re-gated.
                cur.execute(
                    """
                    INSERT INTO oc_admin.calyx_tasks
                        (task_key, task_type, title, payload, status, priority, required_approval)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (task_key) DO UPDATE
                    SET task_type = EXCLUDED.task_type,
                        title = EXCLUDED.title,
                        payload = EXCLUDED.payload,
                        status = EXCLUDED.status,
                        priority = EXCLUDED.priority,
                        required_approval = EXCLUDED.required_approval,
                        last_error = NULL,
                        updated_at = NOW()
                    WHERE oc_admin.calyx_tasks.status IN ('failed', 'blocked')
                    RETURNING *, (xmax = 0) AS was_inserted
                    """,
                    (
                        task_key,
                        task["task_type"],
                        task["title"],
                        _json(payload),
                        status,
                        int(task.get("priority", 0)),
                        bool(task.get("required_approval")),
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    # A live row already covers this finding; leave it alone.
                    cur.execute(
                        "SELECT * FROM oc_admin.calyx_tasks WHERE task_key = %s",
                        (task_key,),
                    )
                    existing = cur.fetchone()
                    conn.commit()
                    return {
                        "created": False,
                        "requeued": False,
                        "task": dict(existing) if existing else None,
                    }

                row = dict(row)
                created = bool(row.pop("was_inserted", False))
                self.orchestrator.log_observation(
                    cur,
                    task_id=row["id"],
                    agent_id=None,
                    event_type="audit_followthrough",
                    action=(
                        ("queued" if status == "pending" else "approval_required")
                        if created
                        else "requeued_after_failure"
                    ),
                    status=status,
                    details={
                        "task_key": task_key,
                        "audit_id": payload.get("audit_id"),
                        "audit_source": payload.get("audit_source"),
                        "finding_key": payload.get("finding_key"),
                        "required_approval": bool(task.get("required_approval")),
                    },
                )
            conn.commit()
        return {"created": created, "requeued": not created, "task": row}


def persist_followthrough(
    findings: Iterable[ActionableFinding],
    store: Any,
    *,
    executor: Optional[DefaultTaskExecutor] = None,
) -> dict[str, Any]:
    """Plan, enforce, and durably persist follow-through for an audit's findings.

    This is the full loop the issue asks for: the dedupe keys of the actionable
    findings are looked up in ``oc_admin.calyx_tasks`` *first*, so duplicate
    suppression is decided against real durable state rather than against a
    caller-supplied guess; the plan is then enforced; and only genuinely new
    tasks are inserted, idempotently.

    Running this twice over the same unchanged findings creates tasks the first
    time and zero the second time -- ``tasks_created`` drops to 0 and every
    finding reports as already in flight.
    """

    findings = list(findings)
    candidate_keys = [
        task_key_for_finding(finding.audit_source, finding.finding_key)
        for finding in findings
        if finding.actionable
    ]
    existing = store.fetch_tasks_by_key(candidate_keys)
    remediations = plan_remediation(
        findings, executor=executor, existing_tasks_by_key=existing
    )
    enforce_followthrough(findings, remediations)

    created = 0
    requeued = 0
    already_present = 0
    persisted: list[dict[str, Any]] = []
    for remediation in remediations:
        if remediation.task is None:
            continue
        outcome = store.insert_task(remediation.task)
        was_created = bool(outcome.get("created"))
        was_requeued = bool(outcome.get("requeued"))
        if was_created:
            created += 1
        elif was_requeued:
            requeued += 1
        else:
            already_present += 1
        persisted.append(
            {
                "finding_key": remediation.finding_key,
                "task_key": remediation.task["task_key"],
                "created": was_created,
                "requeued": was_requeued,
                "required_approval": bool(remediation.task.get("required_approval")),
                "status": str(remediation.task.get("status")),
            }
        )

    return {
        "next_actions_created": next_actions_created(remediations),
        "completion_state": audit_completion_state(remediations),
        "persisted_tasks": persisted,
        "tasks_created": created,
        "tasks_requeued": requeued,
        "tasks_already_present": already_present,
        "existing_tasks_examined": len(existing),
    }
