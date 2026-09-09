"""Lease atomicity audit — Approved Task Priority 28.

Verify queued-to-running transition is atomic before execution and
stale/expired leases are reclaimed safely.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "lease-atomicity-audit/v1"
AUDIT_DATE = "2026-09-09"


class LeaseAtomicityStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class LeaseAtomicityCriterion:
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


LEASE_ATOMICITY_CRITERIA: tuple[LeaseAtomicityCriterion, ...] = (

    # ------------------------------------------------------------------ ATOMIC_CLAIM
    LeaseAtomicityCriterion(
        criterion_id="atomic_claim_for_update_skip_locked",
        area="atomic_claim",
        title="Atomic job claim — FOR UPDATE SKIP LOCKED in PostgresMissionRepository.claim_job()",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "claim_job(): 'SELECT * FROM oc_missions.jobs ... FOR UPDATE SKIP LOCKED'; "
            "atomic single-worker claim — concurrent callers skip locked rows; "
            "no double-claim: database lock enforces mutual exclusion"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="atomic_claim_scheduler_lease_token",
        area="atomic_claim",
        title="Scheduler lease token — claim() sets lease_owner, lease_token, lease_expires_at atomically",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "claim(): atomic update {CalyxJob.lease_owner, CalyxJob.lease_token, CalyxJob.lease_expires_at}; "
            "UUID token generated per claim — prevents stale token replay; "
            "advance_claimed() validates lease_owner and lease_token before mutation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="atomic_claim_lease_duration_bounds",
        area="atomic_claim",
        title="Lease duration bounds — 30 ≤ lease_seconds ≤ 3600 enforced in claim()",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "claim(): 'if not 30 <= lease_seconds <= 3600: raise ValueError'; "
            "bounds prevent arbitrarily short or infinite lease durations; "
            "lease ceiling (3600s) ensures reclaim window is always bounded"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ TRANSITION
    LeaseAtomicityCriterion(
        criterion_id="transition_queued_to_running",
        area="transition",
        title="Queued-to-running transition — start_job() marks job running with worker_id atomically",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "start_job(): updates job state to 'running' with worker_id; "
            "transition validates current state before advancing; "
            "validate_mission_transition(): 'queued' → 'running' is an allowed transition"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="transition_approved_to_queued",
        area="transition",
        title="Approved-to-queued transition — enqueue_due_missions() uses FOR UPDATE SKIP LOCKED",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "enqueue_due_missions(): 'SELECT * FROM ... WHERE state=approved ... FOR UPDATE SKIP LOCKED'; "
            "approved missions atomically transition to queued; "
            "skips locked rows — concurrent schedulers do not double-enqueue"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="transition_validate_mission_transition",
        area="transition",
        title="Transition validation — validate_mission_transition() raises for illegal transitions",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.missions.registry.validate_mission_transition",
        evidence=(
            "validate_mission_transition(): raises ValueError for state transitions not in ALLOWED_TRANSITIONS; "
            "terminal states (superseded, blocked) have limited or no outgoing transitions; "
            "state machine guards against illegal job advancement"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ STALE_RECLAIM
    LeaseAtomicityCriterion(
        criterion_id="stale_reclaim_recover_expired",
        area="stale_reclaim",
        title="Expired lease reclaim — recover_expired_leases() reclaims jobs past lease_expiry",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "recover_expired_leases(): SELECT/UPDATE jobs where lease_expiry <= NOW(); "
            "reclaimed jobs re-enter eligible state for next claim(); "
            "prevents permanent lane lock-out from crashed workers"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="stale_reclaim_scheduler_expired_leases",
        area="stale_reclaim",
        title="Scheduler expired lease handling — claim() skips jobs with expired lease_expires_at",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "claim(): condition CalyxJob.lease_expires_at <= now for reclaim eligibility; "
            "CalyxJob.lease_expires_at.is_not(None) check before reclaim path; "
            "expired leases are re-claimable without manual intervention"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="stale_reclaim_renew_lease_fencing",
        area="stale_reclaim",
        title="Lease fencing on advance — _renew_lease() extends lease during provider calls",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "_renew_lease(): extends lease_expires_at during advance_claimed(); "
            "advance_claimed(): 'Fence the lease across provider and GitHub mutation calls'; "
            "15-minute fenced lease prevents another worker reclaiming the same job mid-operation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    LeaseAtomicityCriterion(
        criterion_id="security_lease_token_validation",
        area="security",
        title="Lease token validation — advance_claimed() validates owner + token before mutation",
        status=LeaseAtomicityStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "advance_claimed(): 'if job.lease_owner != worker_id or job.lease_token != lease_token: raise'; "
            "both owner identity and secret token must match before any mutation; "
            "stale or replayed tokens cannot advance a job they do not own"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LeaseAtomicityCriterion(
        criterion_id="security_durable_lease_requires_db",
        area="security",
        title="Durable lease requires DATABASE_URL — in-memory lease does not survive restarts",
        status=LeaseAtomicityStatus.BLOCKED,
        authoritative_module="app.calyx_engineering.completion_scheduler",
        evidence=(
            "EngineeringCompletionScheduler: backed by SQLAlchemy CalyxJob model; "
            "without DATABASE_URL, lease state is ephemeral — restart loses all leases; "
            "recover_expired_leases() requires persistent DB to be meaningful"
        ),
        gap_description=None,
        blocker_reason="DATABASE_URL not provisioned — lease atomicity is in-memory ephemeral only",
        next_action="Provision DATABASE_URL for durable atomic lease state",
    ),
    LeaseAtomicityCriterion(
        criterion_id="security_no_owner_gate_lease_bypass",
        area="security",
        title="Owner gate cannot be bypassed by lease — OWNER_GATE tasks are never claimable",
        status=LeaseAtomicityStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): OWNER_GATE returned before any claim or dispatch; "
            "OWNER_GATE intents are parked, not enqueued — they have no lease to claim; "
            "lease atomicity does not provide an alternate path past the owner gate"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any OWNER_GATE intent enters the claim queue",
    ),
)


@dataclass
class LeaseAtomicityAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[LeaseAtomicityCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[LeaseAtomicityCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[LeaseAtomicityCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(LeaseAtomicityStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(LeaseAtomicityStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(LeaseAtomicityStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(LeaseAtomicityStatus.OWNER_GATED))

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


def get_lease_atomicity_audit() -> LeaseAtomicityAudit:
    return LeaseAtomicityAudit(criteria=list(LEASE_ATOMICITY_CRITERIA))


def get_criteria_by_status(status: str) -> list[LeaseAtomicityCriterion]:
    return [c for c in LEASE_ATOMICITY_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[LeaseAtomicityCriterion]:
    return [c for c in LEASE_ATOMICITY_CRITERIA if c.area == area]


def get_gaps() -> list[LeaseAtomicityCriterion]:
    return get_criteria_by_status(LeaseAtomicityStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in LEASE_ATOMICITY_CRITERIA
        if c.next_action
    ]
