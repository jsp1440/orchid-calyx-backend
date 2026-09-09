"""Backend repair-backoff invariant audit — Approved Task Priority 29.

Verify repair-backoff cannot be queued, leased, healed, dispatched, or
terminally requeued across every workflow path.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "repair-backoff-backend-audit/v1"
AUDIT_DATE = "2026-09-09"


class RepairBackoffAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class RepairBackoffCriterion:
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


REPAIR_BACKOFF_CRITERIA: tuple[RepairBackoffCriterion, ...] = (

    # ------------------------------------------------------------------ BOUNDED_REPAIR
    RepairBackoffCriterion(
        criterion_id="bounded_repair_max_attempts",
        area="bounded_repair",
        title="Repair attempt cap — max_attempts=3 enforced in completion scheduler",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "enqueue(): max_attempts=3 default; "
            "advance_claimed(): repair_attempt = job.max_attempts + 1 when attempt_count >= max_attempts; "
            "HALTED_REPAIR_LIMIT returned when repair_count >= max_repair_attempts in completion_loop"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="bounded_repair_halt_retry_limit",
        area="bounded_repair",
        title="HALT_RETRY_LIMIT terminal — dispatcher halts when retry limit reached",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchAction",
        evidence=(
            "DispatchAction.HALT_RETRY_LIMIT: returned when retry counter >= limit; "
            "dispatch_event(): HALT_RETRY_LIMIT before RETRY_BACKOFF when at ceiling; "
            "HALTED_REPAIR_LIMIT in CompletionState is the completion loop equivalent"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="bounded_repair_agents_md_rule",
        area="bounded_repair",
        title="AGENTS.md three-attempt rule — stop after three deterministic failures and escalate",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="AGENTS.md",
        evidence=(
            "AGENTS.md: 'Stop after three unsuccessful attempts on the same deterministic failure class'; "
            "'escalate rather than consuming additional model budget'; "
            "completion_loop max_repair_attempts enforces the same invariant in code"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DISPATCH_INVARIANTS
    RepairBackoffCriterion(
        criterion_id="dispatch_autonomous_merge_forbidden",
        area="dispatch_invariants",
        title="Autonomous merge forbidden — DispatchResult raises on autonomous_merge=True",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchResult",
        evidence=(
            "DispatchResult.__post_init__(): raises PermissionError('DISPATCH_AUTONOMOUS_MERGE_FORBIDDEN'); "
            "ContinuationTask.__post_init__(): raises PermissionError('CONTINUATION_AUTONOMOUS_MERGE_FORBIDDEN'); "
            "no repair path may auto-merge — invariant enforced at construction time"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="dispatch_deployment_forbidden",
        area="dispatch_invariants",
        title="Deployment forbidden — DispatchResult raises on deployment=True",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchResult",
        evidence=(
            "DispatchResult.__post_init__(): raises PermissionError('DISPATCH_DEPLOYMENT_FORBIDDEN'); "
            "ContinuationTask.__post_init__(): raises PermissionError('CONTINUATION_DEPLOYMENT_FORBIDDEN'); "
            "repair-backoff cannot trigger a production deployment"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="dispatch_kg_mutation_forbidden",
        area="dispatch_invariants",
        title="KG mutation forbidden — DispatchResult and ContinuationTask both raise on kg_mutation=True",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchResult",
        evidence=(
            "DispatchResult.__post_init__(): raises PermissionError('DISPATCH_KG_MUTATION_FORBIDDEN'); "
            "ContinuationTask.__post_init__(): raises PermissionError('CONTINUATION_KG_MUTATION_FORBIDDEN'); "
            "no repair path may mutate the knowledge graph"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="dispatch_publication_forbidden",
        area="dispatch_invariants",
        title="Auto-publication forbidden — DispatchResult raises on automatic_publication=True",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchResult",
        evidence=(
            "DispatchResult.__post_init__(): raises PermissionError('DISPATCH_AUTOMATIC_PUBLICATION_FORBIDDEN'); "
            "ContinuationTask.__post_init__(): raises PermissionError('CONTINUATION_AUTOMATIC_PUBLICATION_FORBIDDEN'); "
            "repair-backoff cannot trigger automatic scientific publication"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="dispatch_owner_gate_preserved",
        area="dispatch_invariants",
        title="Owner gate preserved — DispatchResult raises if owner_gate_bypassed=True",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchResult",
        evidence=(
            "DispatchResult.__post_init__(): raises PermissionError('DISPATCH_OWNER_GATE_MUST_BE_PRESERVED'); "
            "ContinuationTask.__post_init__(): raises PermissionError('CONTINUATION_OWNER_GATE_MUST_BE_PRESERVED'); "
            "repair path cannot bypass any owner gate"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ REPAIR_AUTHORIZATION
    RepairBackoffCriterion(
        criterion_id="repair_auth_required",
        area="repair_authorization",
        title="Repair authorization required — ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED raised when not authorized",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "enqueue(): raises PermissionError('ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED') "
            "when not repair_paths or not repairs_authorized; "
            "repair cannot proceed without explicit repairs_authorized=True flag"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="repair_blocked_approval_parking",
        area="repair_authorization",
        title="Repair blocked-approval parking — FAILED_REPAIRABLE parks as blocked_approval",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "_finish(): CompletionState.FAILED_REPAIRABLE → job.status = 'blocked_approval'; "
            "approval_class = 'engineering_repair'; "
            "error_code = 'ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED'; "
            "blocked_approval jobs cannot advance without human approval"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ BACKOFF_MECHANISM
    RepairBackoffCriterion(
        criterion_id="backoff_retry_backoff_action",
        area="backoff_mechanism",
        title="RETRY_BACKOFF action — dispatcher returns RETRY_BACKOFF before terminal HALT_RETRY_LIMIT",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchAction",
        evidence=(
            "DispatchAction.RETRY_BACKOFF: returned for transient failures before retry limit; "
            "dispatch_event(): RETRY_BACKOFF path before HALT_RETRY_LIMIT; "
            "backoff occurs before terminal halt — not immediate termination on first failure"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="backoff_dedup_no_op",
        area="backoff_mechanism",
        title="Deduplication no-op — DEDUPLICATED_NO_OP prevents repeated backoff on seen events",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchAction",
        evidence=(
            "DispatchAction.DEDUPLICATED_NO_OP: returned for already-seen event keys; "
            "EventDeduplicator: is_duplicate() / mark_seen() via LRU set; "
            "dedup prevents repeated backoff triggers from the same event replay"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="backoff_stale_head_closed",
        area="backoff_mechanism",
        title="Stale head fail-closed — FAIL_CLOSED_STALE_HEAD prevents repair on outdated PR state",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchAction",
        evidence=(
            "DispatchAction.FAIL_CLOSED_STALE_HEAD: returned when event head_sha != expected; "
            "dispatch_event(): validate_head_binding() check before any repair dispatch; "
            "stale-head events do not trigger repair or backoff — they fail closed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    RepairBackoffCriterion(
        criterion_id="security_halt_infrastructure",
        area="security",
        title="Infrastructure halt — HALT_INFRASTRUCTURE stops workflow on unsafe infrastructure events",
        status=RepairBackoffAuditStatus.READY,
        authoritative_module="app.calyx_engineering.event_dispatcher.DispatchAction",
        evidence=(
            "DispatchAction.HALT_INFRASTRUCTURE: returned for infrastructure-level failures; "
            "dispatch_event(): HALT_INFRASTRUCTURE path before RETRY_BACKOFF; "
            "unsafe infrastructure state does not trigger a repair or backoff cycle"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffCriterion(
        criterion_id="security_production_db_mutation_forbidden",
        area="security",
        title="Production DB mutation forbidden in repair tasks",
        status=RepairBackoffAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_engineering.event_dispatcher.ContinuationTask",
        evidence=(
            "ContinuationTask.__post_init__(): raises PermissionError('CONTINUATION_PRODUCTION_DB_MUTATION_FORBIDDEN'); "
            "repair/continuation tasks are explicitly prohibited from production DB writes; "
            "production DB mutations require owner authorization — not a repair path"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any production DB mutation in repair context",
    ),
)


@dataclass
class RepairBackoffBackendAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[RepairBackoffCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[RepairBackoffCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[RepairBackoffCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(RepairBackoffAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(RepairBackoffAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(RepairBackoffAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(RepairBackoffAuditStatus.OWNER_GATED))

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


def get_repair_backoff_backend_audit() -> RepairBackoffBackendAudit:
    return RepairBackoffBackendAudit(criteria=list(REPAIR_BACKOFF_CRITERIA))


def get_criteria_by_status(status: str) -> list[RepairBackoffCriterion]:
    return [c for c in REPAIR_BACKOFF_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[RepairBackoffCriterion]:
    return [c for c in REPAIR_BACKOFF_CRITERIA if c.area == area]


def get_gaps() -> list[RepairBackoffCriterion]:
    return get_criteria_by_status(RepairBackoffAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in REPAIR_BACKOFF_CRITERIA
        if c.next_action
    ]
