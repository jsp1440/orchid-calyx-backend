"""Exact-head CI audit — Approved Task Priority 33.

Verify merge decisions use current exact head and reject stale, skipped,
cancelled, action_required, or non-substantive checks.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "exact-head-ci-audit/v1"
AUDIT_DATE = "2026-09-09"


class ExactHeadCiAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class ExactHeadCiCriterion:
    criterion_id: str
    area: str
    title: str
    status: str
    authoritative_module: str
    evidence: str
    gap_description: str | None
    blocker_reason: str | None
    next_action: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "area": self.area,
            "title": self.title,
            "status": self.status,
            "authoritative_module": self.authoritative_module,
            "evidence": self.evidence,
            "gap_description": self.gap_description,
            "blocker_reason": self.blocker_reason,
            "next_action": self.next_action,
        }


EXACT_HEAD_CI_CRITERIA: tuple[ExactHeadCiCriterion, ...] = (

    # ------------------------------------------------------------------ HEAD_BINDING
    ExactHeadCiCriterion(
        criterion_id="head_binding_validate_head_sha",
        area="head_binding",
        title="validate_head_binding — exact SHA match required before any continuation or repair",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.validate_head_binding",
        evidence=(
            "validate_head_binding(event_key, expected_head_sha): "
            "event_key.head_sha == expected_head_sha; "
            "returns True (match) or False (stale); "
            "dispatch_event(): mismatch → FAIL_CLOSED_STALE_HEAD with detail 'Head SHA mismatch: event has ... expected ...'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="head_binding_event_key_minimum_sha",
        area="head_binding",
        title="Head SHA minimum length — EventKey rejects blank or short SHAs",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.EventKey",
        evidence=(
            "EventKey.__post_init__(): "
            "not self.head_sha or len(self.head_sha) < 7 → raises ValueError('EVENT_KEY_HEAD_SHA_INVALID'); "
            "minimum 7-character SHA prevents trivial empty-string head binding bypass"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="head_binding_stale_fail_closed",
        area="head_binding",
        title="Stale head fail-closed — FAIL_CLOSED_STALE_HEAD action on SHA mismatch",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchAction",
        evidence=(
            "DispatchAction.FAIL_CLOSED_STALE_HEAD: returned when event SHA != expected SHA; "
            "dispatch_event(): marks event as seen then returns FAIL_CLOSED_STALE_HEAD; "
            "stale head events are deduped and fail closed — never silently ignored or passed forward"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="head_binding_completion_receipt",
        area="head_binding",
        title="Completion receipt binds head SHA — ContinuationTask carries exact head_sha from event",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.ContinuationTask",
        evidence=(
            "create_continuation_task(): task.head_sha = event_key.head_sha; "
            "create_repair_task(): task.head_sha = event_key.head_sha; "
            "CompletionReceipt in completion_loop.py: head_sha per receipt; "
            "every task and receipt carries the exact bound SHA"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ REJECTED_CONCLUSIONS
    ExactHeadCiCriterion(
        criterion_id="rejected_cancelled_infrastructure",
        area="rejected_conclusions",
        title="Cancelled checks rejected — 'cancelled' is an INFRASTRUCTURE conclusion, not success",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher",
        evidence=(
            "_INFRASTRUCTURE_CONCLUSIONS = frozenset({'cancelled', 'timed_out', 'action_required', 'stale'}); "
            "classify_workflow_run_event(): INFRASTRUCTURE conclusions → EventOutcome.INFRASTRUCTURE; "
            "INFRASTRUCTURE outcome → HALT_INFRASTRUCTURE: 'Not repaired; requires owner review'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="rejected_action_required",
        area="rejected_conclusions",
        title="action_required rejected — approval-gated checks cannot satisfy CI success",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher",
        evidence=(
            "_INFRASTRUCTURE_CONCLUSIONS: 'action_required' is classified as INFRASTRUCTURE; "
            "INFRASTRUCTURE → HALT_INFRASTRUCTURE; "
            "action_required checks require owner review — they are never treated as implicit success"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="rejected_skipped_transient",
        area="rejected_conclusions",
        title="Skipped checks are transient — 'skipped' outcome requires retry, not continuation",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher",
        evidence=(
            "_TRANSIENT_CONCLUSIONS = frozenset({'skipped'}); "
            "classify_workflow_run_event(): TRANSIENT → EventOutcome.TRANSIENT; "
            "TRANSIENT: retry if retry_count < MAX_TRANSIENT_RETRIES else HALT_RETRY_LIMIT; "
            "skipped checks do not qualify as CI success and trigger bounded retry, not continuation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="rejected_stale_conclusion",
        area="rejected_conclusions",
        title="Stale conclusion rejected — 'stale' is an INFRASTRUCTURE outcome, requires owner review",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher",
        evidence=(
            "_INFRASTRUCTURE_CONCLUSIONS: 'stale' is classified as INFRASTRUCTURE; "
            "stale check results cannot satisfy CI success criteria; "
            "HALT_INFRASTRUCTURE returned — stale checks go to owner review"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SUBSTANTIVE_CHECKS
    ExactHeadCiCriterion(
        criterion_id="substantive_success_only",
        area="substantive_checks",
        title="Only explicit 'success' qualifies — 'neutral' and 'failure' are not continuation-eligible",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher",
        evidence=(
            "_SUCCESS_CONCLUSIONS = frozenset({'success'}); "
            "_FAILURE_CONCLUSIONS = frozenset({'failure', 'neutral'}); "
            "classify_workflow_run_event(): FAILURE for 'neutral' — 'neutral' does not count as success; "
            "only explicit 'success' triggers ENQUEUE_CONTINUATION"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="substantive_pending_await",
        area="substantive_checks",
        title="Pending checks await — in-progress CI does not trigger continuation",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher",
        evidence=(
            "classify_workflow_run_event(): conclusion is None or 'in_progress' → EventOutcome.PENDING; "
            "dispatch_event(): PENDING → DispatchAction.AWAIT_COMPLETION; "
            "in-progress CI cannot advance the workflow — await conclusion before acting"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEDUPLICATION
    ExactHeadCiCriterion(
        criterion_id="dedup_idempotency_key",
        area="deduplication",
        title="Idempotency key — SHA-256 of repo:pr:head_sha:run_id:event_kind prevents duplicate dispatch",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.EventKey",
        evidence=(
            "EventKey.idempotency_key: sha256(f'{repo}:{pr}:{head_sha}:{run_id}:{event_kind}')[:32]; "
            "EventDeduplicator.is_duplicate(): returns True if idempotency_key already seen; "
            "dispatch_event(): duplicate → DEDUPLICATED_NO_OP before any other processing"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ExactHeadCiCriterion(
        criterion_id="dedup_stale_head_marked_seen",
        area="deduplication",
        title="Stale head marked seen — FAIL_CLOSED_STALE_HEAD marks event to prevent re-processing",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.dispatch_event",
        evidence=(
            "dispatch_event(): stale head check → deduplicator.mark_seen(event_key) then FAIL_CLOSED_STALE_HEAD; "
            "stale-head event is deduped immediately — replayed delivery of the same stale event → no-op"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    ExactHeadCiCriterion(
        criterion_id="security_no_auto_merge",
        area="security",
        title="No auto-merge — merge decisions are owner-gated even after exact-head CI success",
        status=ExactHeadCiAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchResult",
        evidence=(
            "DispatchResult.__post_init__(): autonomous_merge=True → raises PermissionError('DISPATCH_AUTONOMOUS_MERGE_FORBIDDEN'); "
            "ContinuationTask.__post_init__(): autonomous_merge=True → raises PermissionError('CONTINUATION_AUTONOMOUS_MERGE_FORBIDDEN'); "
            "CI success enables continuation, not automatic merge — merge still requires owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any PR merge even after exact-head CI success",
    ),
    ExactHeadCiCriterion(
        criterion_id="security_infrastructure_halt_no_repair",
        area="security",
        title="Infrastructure conclusions halt — HALT_INFRASTRUCTURE is never repaired autonomously",
        status=ExactHeadCiAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.dispatch_event",
        evidence=(
            "dispatch_event(): INFRASTRUCTURE → HALT_INFRASTRUCTURE; "
            "detail: 'Infrastructure failure (cancelled/timed_out/action_required/stale). Not repaired; requires owner review'; "
            "no repair task is created for INFRASTRUCTURE outcomes — they go directly to owner"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
)


@dataclass
class ExactHeadCiAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[ExactHeadCiCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[ExactHeadCiCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[ExactHeadCiCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(ExactHeadCiAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(ExactHeadCiAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(ExactHeadCiAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(ExactHeadCiAuditStatus.OWNER_GATED))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audit_date": self.audit_date,
            "no_auto_publication": self.no_auto_publication,
            "no_production_mutation": self.no_production_mutation,
            "summary": {
                "total": len(self.criteria),
                "ready": self.ready_count(),
                "gap": self.gap_count(),
                "blocked": self.blocked_count(),
                "owner_gated": self.owner_gated_count(),
            },
            "criteria": [c.to_dict() for c in self.criteria],
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)


def get_exact_head_ci_audit() -> ExactHeadCiAudit:
    return ExactHeadCiAudit(criteria=list(EXACT_HEAD_CI_CRITERIA))


def get_criteria_by_status(status: str) -> list[ExactHeadCiCriterion]:
    return [c for c in EXACT_HEAD_CI_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[ExactHeadCiCriterion]:
    return [c for c in EXACT_HEAD_CI_CRITERIA if c.area == area]


def get_gaps() -> list[ExactHeadCiCriterion]:
    return get_criteria_by_status(ExactHeadCiAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in EXACT_HEAD_CI_CRITERIA
        if c.next_action
    ]
