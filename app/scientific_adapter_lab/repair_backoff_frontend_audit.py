"""Frontend repair-backoff invariant audit — Approved Task Priority 31.

Verify repair/runtime backoff cannot be re-admitted by healer, scheduler,
dispatcher, or settlement paths.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "repair-backoff-frontend-audit/v1"
AUDIT_DATE = "2026-09-09"


class RepairBackoffFrontendAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class RepairBackoffFrontendCriterion:
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


REPAIR_BACKOFF_FRONTEND_CRITERIA: tuple[RepairBackoffFrontendCriterion, ...] = (

    # ------------------------------------------------------------------ HEALER
    RepairBackoffFrontendCriterion(
        criterion_id="healer_repair_backoff_state",
        area="healer",
        title="REPAIR_BACKOFF state — deep_orchestrate has a dedicated REPAIR_BACKOFF state distinct from BLOCKED",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.TaskState",
        evidence=(
            "TaskState.REPAIR_BACKOFF = 'repair_backoff'; "
            "TaskState enum: READY | LEASED | RUNNING | VALIDATING | COMPLETED | BLOCKED | OWNER_GATED | REPAIR_BACKOFF; "
            "REPAIR_BACKOFF is not in _TERMINAL or _ACTIVE — it is its own distinct non-executable state"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="healer_enter_repair_backoff",
        area="healer",
        title="enter_repair_backoff — transition sets state, clears lease; task cannot execute while in backoff",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.DeepOrchestrate",
        evidence=(
            "enter_repair_backoff(key, reason): "
            "leaf.state = TaskState.REPAIR_BACKOFF; "
            "leaf.leased_at = None; leaf.lease_holder = None; "
            "_is_ready(): returns False for any state != TaskState.READY; "
            "repair_backoff task cannot be leased until explicitly recovered"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="healer_recover_from_backoff",
        area="healer",
        title="recover_from_backoff — only explicit call restores to READY; cannot self-recover",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.DeepOrchestrate",
        evidence=(
            "recover_from_backoff(key): "
            "raises ValueError(f'NOT_IN_BACKOFF:{key}:state={leaf.state}') if state != REPAIR_BACKOFF; "
            "owner-gated tasks → OWNER_GATED, others → READY; "
            "no time-based self-recovery path — requires explicit method call"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SCHEDULER
    RepairBackoffFrontendCriterion(
        criterion_id="scheduler_is_ready_excludes_backoff",
        area="scheduler",
        title="_is_ready excludes REPAIR_BACKOFF — backoff tasks never enter the ready candidate pool",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.DeepOrchestrate._is_ready",
        evidence=(
            "_is_ready(leaf): leaf.state != TaskState.READY → return False; "
            "REPAIR_BACKOFF != READY → _is_ready returns False; "
            "ready_tasks(): [t for t in self._tasks.values() if self._is_ready(t)]; "
            "repair_backoff tasks cannot appear in ready_tasks() output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="scheduler_refill_excludes_backoff",
        area="scheduler",
        title="refill excludes REPAIR_BACKOFF — capacity refill cannot re-admit backoff tasks",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.DeepOrchestrate.refill",
        evidence=(
            "refill(): calls ready_tasks(limit=slots) which calls _is_ready(); "
            "_is_ready() returns False for REPAIR_BACKOFF; "
            "backoff tasks do not consume active slots — slot count is from active_tasks() "
            "which is [t.state in _ACTIVE]; REPAIR_BACKOFF not in _ACTIVE"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="scheduler_cycle_bounded",
        area="scheduler",
        title="Cycle bounded — execute_all_pending_jobs() drains at most max_jobs per cycle",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="runtime.autonomous_runner.execute_all_pending_jobs",
        evidence=(
            "execute_all_pending_jobs(max_jobs=10): for _ in range(max_jobs): ...; "
            "returns {'status': 'cycle_limit_reached'} after max_jobs iterations; "
            "ProgramAutonomyPolicy.max_jobs_per_cycle gates run_deterministic_program_cycle; "
            "bounded cycle prevents unbounded repair-backoff re-admission"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DISPATCHER
    RepairBackoffFrontendCriterion(
        criterion_id="dispatcher_repair_backoff_anomaly",
        area="dispatcher",
        title="repair_backoff_contradiction anomaly — exception_policy classifies it as engineering exception",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.autonomy.exception_policy",
        evidence=(
            "ENGINEERING_ANOMALIES includes 'repair_backoff_contradiction'; "
            "classify_exception('repair_backoff_contradiction'): "
            "exception_class='engineering_exception', owner_decision_required=False; "
            "action='repair' if autonomous_repair_available else 'continue_other_authorized_work' "
            "or 'park_and_reconcile'; backoff contradiction is never escalated to owner unless "
            "no work and no repair available"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="dispatcher_queue_backoff_anomaly",
        area="dispatcher",
        title="queue_backoff_contradiction anomaly — classified as engineering exception, not owner escalation",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.autonomy.exception_policy",
        evidence=(
            "ENGINEERING_ANOMALIES includes 'queue_backoff_contradiction'; "
            "classify_exception('queue_backoff_contradiction'): engineering_exception path; "
            "should_interrupt_owner=False; owner interruption only when no repair and no independent work; "
            "queue backoff contradiction is self-healable, not owner-gated"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="dispatcher_owner_gate_isolation",
        area="dispatcher",
        title="Owner-gate isolation — owner_exception categories are distinct from backoff path",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="app.autonomy.exception_policy.PROTECTED_BOUNDARIES",
        evidence=(
            "PROTECTED_BOUNDARIES: 8 categories (governance | scientific_activation | "
            "sensitive_locality | credential_security | spending_provider_restoration | "
            "destructive_irreversible | production_activation | integration_main_promotion); "
            "none of these map to repair_backoff or queue_backoff; "
            "owner escalation on protected_boundary cannot be triggered by backoff path"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SETTLEMENT
    RepairBackoffFrontendCriterion(
        criterion_id="settlement_failed_not_re_queued",
        area="settlement",
        title="Failed jobs not re-queued — status 'failed' is terminal in execution job runner",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="runtime.autonomous_runner.execute_next_job",
        evidence=(
            "execute_next_job(): exception → SET status='failed', retry_count += 1; "
            "execute_all_pending_jobs(): status=='failed' → failed += 1; continue; "
            "no re-queue on failure — failed jobs stay failed; "
            "dedup_key UNIQUE prevents re-insertion for same job name"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="settlement_retry_requires_api_call",
        area="settlement",
        title="Retry requires explicit API call — executor retry is not automatic on failure",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="runtime.executor_router",
        evidence=(
            "executor_router: POST /api/runner/retry/{execution_id} requires verify_api_key; "
            "RuntimeExecutor.retry(): calls execute_module(record['module_id']); "
            "retry is an explicit owner-authorized API call, not an automatic re-admission path; "
            "no background job silently re-queues a failed execution"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="settlement_cancelled_not_re_admitted",
        area="settlement",
        title="Cancelled executions not re-admitted — 'cancelled' is a terminal state",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="runtime.runtime_executor.RuntimeExecutor",
        evidence=(
            "RuntimeExecutor.cancel(): status in {'completed', 'completed_degraded', 'failed', 'cancelled'} "
            "→ 'not_cancellable'; "
            "cancel() sets status='cancelled' and appends 'execution_cancelled' event; "
            "no execution path re-admits a cancelled execution"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    RepairBackoffFrontendCriterion(
        criterion_id="security_autonomy_not_authorized",
        area="security",
        title="Autonomy authorization required — run_once() checks authorized before any dispatch",
        status=RepairBackoffFrontendAuditStatus.READY,
        authoritative_module="runtime.program_autonomy_worker.run_once",
        evidence=(
            "run_once(): active_policy.status()['authorized'] is False → "
            "return {'executed': False, 'reason': 'disabled_or_owner_not_configured'}; "
            "run_forever(): not status['authorized'] → raises PermissionError('PROGRAM_AUTONOMY_NOT_AUTHORIZED'); "
            "autonomy cycle cannot start without explicit owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RepairBackoffFrontendCriterion(
        criterion_id="security_repair_owner_protection_preserved",
        area="security",
        title="Owner protection preserved — PROTECTED_BOUNDARIES cannot be bypassed by repair-backoff path",
        status=RepairBackoffFrontendAuditStatus.OWNER_GATED,
        authoritative_module="app.autonomy.exception_policy.PROTECTED_BOUNDARIES",
        evidence=(
            "classify_exception(protected_boundary=...): category = PROTECTED_BOUNDARIES.get(...); "
            "if category is not None and not (autonomous_repair_available or independent_work): "
            "exception_class='owner_exception', owner_decision_required=True, should_interrupt_owner=True; "
            "no repair-backoff path can override a protected boundary — owner authorization required"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any action crossing a PROTECTED_BOUNDARIES category",
    ),
)


@dataclass
class RepairBackoffFrontendAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[RepairBackoffFrontendCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[RepairBackoffFrontendCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[RepairBackoffFrontendCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(RepairBackoffFrontendAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(RepairBackoffFrontendAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(RepairBackoffFrontendAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(RepairBackoffFrontendAuditStatus.OWNER_GATED))

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


def get_repair_backoff_frontend_audit() -> RepairBackoffFrontendAudit:
    return RepairBackoffFrontendAudit(criteria=list(REPAIR_BACKOFF_FRONTEND_CRITERIA))


def get_criteria_by_status(status: str) -> list[RepairBackoffFrontendCriterion]:
    return [c for c in REPAIR_BACKOFF_FRONTEND_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[RepairBackoffFrontendCriterion]:
    return [c for c in REPAIR_BACKOFF_FRONTEND_CRITERIA if c.area == area]


def get_gaps() -> list[RepairBackoffFrontendCriterion]:
    return get_criteria_by_status(RepairBackoffFrontendAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in REPAIR_BACKOFF_FRONTEND_CRITERIA
        if c.next_action
    ]
