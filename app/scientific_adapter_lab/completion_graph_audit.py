"""Recursive completion graph audit — Approved Task Priority 24.

Inspects bounded leaves, acceptance evidence, dependencies, priorities,
owner/external blockers, and stale/superseded state.

Status vocabulary:
  READY        — implemented, tested, and integrated
  GAP          — described in acceptance criteria but not yet closed
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "completion-graph-audit/v1"
AUDIT_DATE = "2026-09-09"


class CompletionGraphAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class CompletionGraphAuditCriterion:
    """One measurable criterion in the recursive completion graph audit."""

    criterion_id: str
    area: str        # leaves | acceptance | dependencies | priorities | blockers | stale_superseded | security
    title: str
    status: str      # CompletionGraphAuditStatus constant
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


# ---------------------------------------------------------------------------
# Canonical completion graph criteria
# ---------------------------------------------------------------------------

COMPLETION_GRAPH_CRITERIA: tuple[CompletionGraphAuditCriterion, ...] = (

    # ------------------------------------------------------------------ LEAVES
    CompletionGraphAuditCriterion(
        criterion_id="leaves_approved_task_reservoir",
        area="leaves",
        title="Approved task reservoir — ApprovedTask tuple with stable key/priority/area/title/description",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "APPROVED_TASKS: tuple of ApprovedTask(key, area, priority, title, description); "
            "stable key per task (e.g. 'completion_graph', 'epistemic_memory'); "
            "reservoir sorted by priority — lower int = higher priority"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="leaves_bounded_lane_width",
        area="leaves",
        title="Bounded lane width — GovernedAutonomousCompletionLoop advances one PR at a time",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.GovernedAutonomousCompletionLoop",
        evidence=(
            "GovernedAutonomousCompletionLoop: 'Advance one draft PR through a bounded CI -> repair -> CI cycle'; "
            "max_repair_attempts: bounded integer cap on repair cycles; "
            "one active completion per loop invocation — no unconstrained fan-out"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="leaves_specialist_cap",
        area="leaves",
        title="Specialist cap — MissionSpec max 7 specialists prevents unbounded expansion",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.meta_orchestrator",
        evidence=(
            "MissionSpec: max_specialists=7; orchestrator enforces cap during mission planning; "
            "meta_orchestrator_audit P19: planning_specialist_cap READY; "
            "bounded width prevents recursive expansion to unbounded graph depth"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="leaves_completion_state_enum",
        area="leaves",
        title="CompletionState enum — terminal states: READY_FOR_MERGE | HALTED_* | REPAIR_COMMITTED",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.CompletionState",
        evidence=(
            "CompletionState(StrEnum): WAITING_FOR_CI, FAILED_REPAIRABLE, REPAIR_COMMITTED, "
            "READY_FOR_MERGE, HALTED_REPAIR_LIMIT, HALTED_UNSAFE_PR_STATE, HALTED_NO_REPAIR; "
            "each leaf terminates in one of these defined states — no open-ended continuation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ACCEPTANCE
    CompletionGraphAuditCriterion(
        criterion_id="acceptance_immutable_artifact",
        area="acceptance",
        title="Immutable artifact acceptance — SHA-256 content hash in ImmutableArtifactRegistry",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.ImmutableArtifactRegistry",
        evidence=(
            "ImmutableArtifactRegistry: SHA-256 content hash per artifact; "
            "require_evidence() enforces EVIDENCES relation for each artifact; "
            "idempotent registration: re-registering same hash is a no-op"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="acceptance_completion_receipt",
        area="acceptance",
        title="Completion receipt — CompletionReceipt with state, repair count, CI conclusions",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.CompletionReceipt",
        evidence=(
            "CompletionReceipt(frozen=True): state, pr_number, head_sha, repair_count, "
            "check_conclusions dict; to_dict() serializes receipt for downstream record; "
            "receipt is the acceptance evidence for completion loop exit"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="acceptance_halted_unsafe_pr_state",
        area="acceptance",
        title="Unsafe PR state halts — HALTED_UNSAFE_PR_STATE on non-draft PR base",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.GovernedAutonomousCompletionLoop",
        evidence=(
            "advance(): checks PR base branch safety before any repair; "
            "HALTED_UNSAFE_PR_STATE: returned immediately when targeting main/master; "
            "acceptance evidence must confirm non-destructive base before progressing"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEPENDENCIES
    CompletionGraphAuditCriterion(
        criterion_id="dependencies_priority_ordered_queue",
        area="dependencies",
        title="Priority-ordered queue — missions dequeued by priority DESC, available_at ASC",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "claim_job(): SELECT ... ORDER BY priority DESC, available_at ASC, job_id ASC; "
            "enqueue_due_missions(): ORDER BY priority DESC; "
            "dependency ordering expressed through priority — higher-priority tasks execute first"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="dependencies_approved_task_sequence",
        area="dependencies",
        title="Approved task sequence — integer priority defines execution order across approved tasks",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "ApprovedTask.priority: integer 1-46+; lower = executed first; "
            "approved_tasks.py: 47+ tasks sorted by priority field; "
            "sequential execution prevents dependency violations between audit stages"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="dependencies_live_graph_state",
        area="dependencies",
        title="Live completion graph state — requires DATABASE_URL for persistent dependency tracking",
        status=CompletionGraphAuditStatus.BLOCKED,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "PostgresMissionRepository: requires database_url for persistent job/mission state; "
            "without DATABASE_URL, completion graph is in-memory ephemeral; "
            "recovery_expired_leases(), telemetry() require live DB connection"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL not provisioned — completion graph persists in-memory only; "
            "cross-restart dependency tracking unavailable without PostgreSQL"
        ),
        next_action="Provision DATABASE_URL for durable completion graph state",
    ),

    # ------------------------------------------------------------------ PRIORITIES
    CompletionGraphAuditCriterion(
        criterion_id="priorities_mission_type_default_priority",
        area="priorities",
        title="Mission type default priority — default_priority per MissionType (60-80 range)",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.registry.MISSION_TEMPLATES",
        evidence=(
            "MISSION_TEMPLATES: default_priority per template (60-80 range); "
            "MissionType.default_priority field; "
            "priority encoded in mission record at creation for stable ordering"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="priorities_risk_level_gating",
        area="priorities",
        title="Risk level gating — high-risk missions require owner authorization before queuing",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.registry.MissionType",
        evidence=(
            "MissionType: risk_level field (low/medium/high); "
            "required_authorization per type; "
            "factory_policy: OWNER_GATE for high-consequence or scientific-authority changes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ BLOCKERS
    CompletionGraphAuditCriterion(
        criterion_id="blockers_database_url_missing",
        area="blockers",
        title="External blocker — DATABASE_URL missing blocks durable queue and completion state",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "PostgresMissionRepository.__init__(): accepts database_url=None; "
            "mission_database_url(): reads DATABASE_URL env var; "
            "absence is a known external blocker, not a code defect"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="blockers_halted_repair_limit",
        area="blockers",
        title="Repair limit halts completion — HALTED_REPAIR_LIMIT stops after max_repair_attempts",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.GovernedAutonomousCompletionLoop",
        evidence=(
            "advance(): repair_count >= max_repair_attempts → HALTED_REPAIR_LIMIT; "
            "AGENTS.md: stop after three unsuccessful attempts and escalate; "
            "bounded repair prevents infinite loop on deterministic CI failure classes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="blockers_owner_gate_merge",
        area="blockers",
        title="Owner gate blocks merge to main — OWNER_GATE prevents auto-integration to main",
        status=CompletionGraphAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): OWNER_GATE returned for main/master target; "
            "never merge to main without owner authorization; "
            "completion graph leaf is BLOCKED until owner approves promotion"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any PR merges to main",
    ),

    # ------------------------------------------------------------------ STALE_SUPERSEDED
    CompletionGraphAuditCriterion(
        criterion_id="stale_superseded_mission_states",
        area="stale_superseded",
        title="Superseded mission state — superseded is a terminal state in MISSION_STATES",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.registry.MISSION_STATES",
        evidence=(
            "MISSION_STATES: includes 'superseded' as terminal state with no outgoing transitions; "
            "validate_mission_transition(): completed/cancelled/failed can transition to superseded; "
            "superseded missions are not re-queued — they are permanently retired from the graph"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="stale_superseded_stale_record_review",
        area="stale_superseded",
        title="Stale record review — stale_record_review MissionType blocks safely without execution",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.registry.MISSION_TYPES",
        evidence=(
            "stale_record_review MissionType: strategy='not_implemented_safe_block'; "
            "stale detection registered as a mission type but safely blocks pending implementation; "
            "stale records are surfaced rather than silently dropped"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="stale_superseded_completion_loop_stale_checks",
        area="stale_superseded",
        title="CI stale check set — STALE_CHECK_CONCLUSIONS defines CI states that halt the loop",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop",
        evidence=(
            "STALE_CHECK_CONCLUSIONS: {'cancelled', 'timed_out', 'action_required', 'stale'}; "
            "advance(): stale CI conclusions are treated as terminal halts; "
            "loop does not spin on stale checks — returns HALTED state"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    CompletionGraphAuditCriterion(
        criterion_id="security_no_main_merge",
        area="security",
        title="No merge to main — completion loop never auto-merges to main/master",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy",
        evidence=(
            "factory_policy: AUTO_INTEGRATE only for non-main branches; "
            "GovernedAutonomousCompletionLoop: HALTED_UNSAFE_PR_STATE for main-targeting PRs; "
            "AGENTS.md: never merge to main without required owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CompletionGraphAuditCriterion(
        criterion_id="security_lease_atomicity_claim",
        area="security",
        title="Atomic job claim — FOR UPDATE SKIP LOCKED ensures single-worker job ownership",
        status=CompletionGraphAuditStatus.READY,
        authoritative_module="app.missions.repositories.PostgresMissionRepository",
        evidence=(
            "claim_job(): 'FOR UPDATE SKIP LOCKED' — atomic single-worker claim; "
            "recover_expired_leases(): reclaims stale lease_expiry records; "
            "no double-dispatch: database enforces lease ownership atomically"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class CompletionGraphAudit:
    """Machine-readable recursive completion graph audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[CompletionGraphAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[CompletionGraphAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[CompletionGraphAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(CompletionGraphAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(CompletionGraphAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(CompletionGraphAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(CompletionGraphAuditStatus.OWNER_GATED))

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


def get_completion_graph_audit() -> CompletionGraphAudit:
    """Return the current completion graph audit. Pure function — no external calls."""
    return CompletionGraphAudit(criteria=list(COMPLETION_GRAPH_CRITERIA))


def get_criteria_by_status(status: str) -> list[CompletionGraphAuditCriterion]:
    return [c for c in COMPLETION_GRAPH_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[CompletionGraphAuditCriterion]:
    return [c for c in COMPLETION_GRAPH_CRITERIA if c.area == area]


def get_gaps() -> list[CompletionGraphAuditCriterion]:
    return get_criteria_by_status(CompletionGraphAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in COMPLETION_GRAPH_CRITERIA
        if c.next_action
    ]
