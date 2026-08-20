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
  remediation.

High-risk task types are routed through the existing
``DefaultTaskExecutor.risky_action`` owner-gate in
``runtime.autonomous_orchestrator`` rather than a second, parallel notion of
"risky" defined here.
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

DEFAULT_TASK_TYPE = "audit_followthrough_remediation"


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
    """The outcome of classifying one finding: its disposition and any task."""

    finding_key: str
    disposition: str
    task: Optional[dict[str, Any]] = None
    rationale: str = ""

    def __post_init__(self) -> None:
        validate_disposition(self.disposition)


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
        finding_key=finding.finding_key, disposition=disposition, task=task, rationale=rationale
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
                )
            )
        elif status in {"pending", "running"}:
            plans.append(
                FindingRemediation(
                    finding_key=finding.finding_key,
                    disposition="in_progress",
                    task=None,
                    rationale=f"existing task {key} already {status}; not duplicating",
                )
            )
        elif status == "needs_review":
            plans.append(
                FindingRemediation(
                    finding_key=finding.finding_key,
                    disposition="owner_approval_required",
                    task=None,
                    rationale=f"existing task {key} is waiting on the owner-approval gate",
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
    """Fail closed if any actionable finding has no disposition at all.

    A disposition value outside the seven terminal states is already
    impossible by construction (``FindingRemediation.__post_init__``
    validates it), so the remaining structural failure mode this guards
    against is a finding being dropped -- narrated in a report but never
    actually classified. That is exactly the "narrative-only completion"
    failure mode #1025 exists to close off.
    """

    remediated_keys = {remediation.finding_key for remediation in remediations}
    missing = [
        finding.finding_key for finding in findings if finding.finding_key not in remediated_keys
    ]
    if missing:
        raise NarrativeOnlyCompletionError(
            "audit cannot be reported complete: actionable findings without a "
            f"disposition: {sorted(missing)}"
        )


def next_actions_created(remediations: Iterable[FindingRemediation]) -> list[dict[str, Any]]:
    """The owner-facing summary shape: what follow-through actually happened."""

    return [
        {
            "finding_key": remediation.finding_key,
            "disposition": remediation.disposition,
            "task_key": (remediation.task or {}).get("task_key"),
            "required_approval": bool((remediation.task or {}).get("required_approval")),
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
    }
