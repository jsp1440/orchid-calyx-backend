"""No-idle lane refill audit — Approved Task Priority 26.

Verify eligible safe capacity is immediately refilled after completion,
block, provider wait, or CI wait.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "lane-refill-audit/v1"
AUDIT_DATE = "2026-09-09"


class LaneRefillAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class LaneRefillAuditCriterion:
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


LANE_REFILL_CRITERIA: tuple[LaneRefillAuditCriterion, ...] = (

    # ------------------------------------------------------------------ COMPLETION_REFILL
    LaneRefillAuditCriterion(
        criterion_id="completion_run_once_refill",
        area="completion_refill",
        title="run_once refill — scheduler.run_once() claims next eligible job after completion",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "run_once(): claim() → advance_claimed() → _finish(); "
            "next call to run_once() immediately claims the next eligible job; "
            "no idle gap between completion of one job and claim of the next"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LaneRefillAuditCriterion(
        criterion_id="completion_idle_reason",
        area="completion_refill",
        title="Idle detection — run_once() returns 'idle' reason when no job available",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "run_once(): returns {'executed': False, 'reason': 'idle'} when claim() returns None; "
            "idle signal is explicit — allows caller to distinguish idle from error; "
            "no-idle intent: loop is re-triggered as soon as a job becomes available"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ BLOCK_REFILL
    LaneRefillAuditCriterion(
        criterion_id="block_refill_blocked_approval",
        area="block_refill",
        title="Blocked-approval parking — job transitions to blocked_approval without blocking the lane",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "_finish(): job.status = 'blocked_approval' when approval_class set; "
            "blocked_approval jobs do not occupy the active claim slot; "
            "lane refills immediately from next eligible job in reservoir"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LaneRefillAuditCriterion(
        criterion_id="block_refill_mission_blocked_state",
        area="block_refill",
        title="Mission blocked state — missions in 'blocked' state remain in queue without lane occupancy",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.missions.registry.MISSION_STATES",
        evidence=(
            "MISSION_STATES: 'blocked' → {'superseded'} only; "
            "blocked missions do not advance to 'running'; "
            "claim_job() ORDER BY priority — blocked missions do not compete for the active slot"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVIDER_WAIT_REFILL
    LaneRefillAuditCriterion(
        criterion_id="provider_wait_park_provider_required",
        area="provider_wait_refill",
        title="Provider-wait park — PARK_PROVIDER_REQUIRED parks the intent without blocking the lane",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryAction",
        evidence=(
            "FactoryAction.PARK_PROVIDER_REQUIRED: intent is parked, not failed; "
            "evaluate_factory_gate(): PARK_PROVIDER_REQUIRED returned immediately; "
            "lane is not occupied during provider wait — next eligible task can be claimed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LaneRefillAuditCriterion(
        criterion_id="provider_wait_no_api_mode",
        area="provider_wait_refill",
        title="NO-API mode provider wait — all provider-required tasks parked until constraint lifted",
        status=LaneRefillAuditStatus.BLOCKED,
        authoritative_module="app.calyx_orchestrator.factory_policy",
        evidence=(
            "evaluate_factory_gate(): provider_required=True + no_api_mode=True → PARK_PROVIDER_REQUIRED; "
            "provider-dependent lane items cannot be refilled while NO-API mode is active; "
            "non-provider tasks continue to refill the lane normally"
        ),
        gap_description=None,
        blocker_reason="NO-API mode active — provider-required lane items blocked from execution",
        next_action="Lift NO-API constraint to allow provider-dependent lane refill",
    ),

    # ------------------------------------------------------------------ CI_WAIT_REFILL
    LaneRefillAuditCriterion(
        criterion_id="ci_wait_waiting_state",
        area="ci_wait_refill",
        title="CI wait state — WAITING_FOR_CI state parks completion loop without blocking the scheduler",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.CompletionState",
        evidence=(
            "CompletionState.WAITING_FOR_CI: advance() returns this when CI is pending; "
            "scheduler re-runs advance_claimed() on next poll cycle; "
            "CI-waiting jobs hold their claim slot during wait — one job per active loop"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LaneRefillAuditCriterion(
        criterion_id="ci_wait_repair_committed",
        area="ci_wait_refill",
        title="Repair committed refills CI — REPAIR_COMMITTED re-enters CI wait with fresh head",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.CompletionState",
        evidence=(
            "CompletionState.REPAIR_COMMITTED: repair pushed, now waiting for CI again; "
            "advance(): REPAIR_COMMITTED increments repair_count, re-enters WAITING_FOR_CI; "
            "lane continues (same job) without idle gap after repair"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    LaneRefillAuditCriterion(
        criterion_id="security_lease_claim_atomicity",
        area="security",
        title="Atomic lane claim — claim() uses atomic DB update to prevent double-refill",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "claim(): atomic update with lease_owner / lease_token / lease_expires_at; "
            "multiple workers calling claim() concurrently each get distinct jobs; "
            "refill is safe: no two workers claim the same slot"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LaneRefillAuditCriterion(
        criterion_id="security_no_owner_gate_bypass",
        area="security",
        title="Owner-gated items never refill active lane — OWNER_GATE tasks do not auto-advance",
        status=LaneRefillAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): OWNER_GATE returned for high-consequence tasks; "
            "OWNER_GATE items cannot be claimed or advanced without authorization; "
            "lane does not silently refill with owner-gated work"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before owner-gated items enter the active lane",
    ),
    LaneRefillAuditCriterion(
        criterion_id="security_expired_lease_reclaim",
        area="security",
        title="Expired lease reclaim — recover_expired_leases() prevents stale job lock-out",
        status=LaneRefillAuditStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "recover_expired_leases(): reclaims jobs with expired lease_expiry; "
            "stale leases do not permanently block lane slot; "
            "lease recovery makes the slot available for normal refill"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
)


@dataclass
class LaneRefillAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[LaneRefillAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[LaneRefillAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[LaneRefillAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(LaneRefillAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(LaneRefillAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(LaneRefillAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(LaneRefillAuditStatus.OWNER_GATED))

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


def get_lane_refill_audit() -> LaneRefillAudit:
    return LaneRefillAudit(criteria=list(LANE_REFILL_CRITERIA))


def get_criteria_by_status(status: str) -> list[LaneRefillAuditCriterion]:
    return [c for c in LANE_REFILL_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[LaneRefillAuditCriterion]:
    return [c for c in LANE_REFILL_CRITERIA if c.area == area]


def get_gaps() -> list[LaneRefillAuditCriterion]:
    return get_criteria_by_status(LaneRefillAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in LANE_REFILL_CRITERIA
        if c.next_action
    ]
