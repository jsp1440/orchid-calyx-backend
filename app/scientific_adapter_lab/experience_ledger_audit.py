"""Experience Ledger audit — Approved Task Priority 21.

Inspects empirical outcome capture, replayable evidence, failure learning,
provider outcomes, and planning feedback.

Status vocabulary:
  READY        — implemented, tested, and integrated
  GAP          — described in acceptance criteria but not yet closed
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No production KG mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "experience-ledger-audit/v1"
AUDIT_DATE = "2026-09-09"


class LedgerAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class LedgerAuditCriterion:
    """One measurable criterion in the experience ledger audit."""

    criterion_id: str
    area: str        # outcome_capture | replay | failure | provider | planning | security | durable
    title: str
    status: str      # LedgerAuditStatus constant
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
# Canonical experience ledger criteria
# ---------------------------------------------------------------------------

LEDGER_AUDIT_CRITERIA: tuple[LedgerAuditCriterion, ...] = (

    # ------------------------------------------------------------------ OUTCOME_CAPTURE
    LedgerAuditCriterion(
        criterion_id="outcome_capture_program_job",
        area="outcome_capture",
        title="Program job outcome capture — record_outcome() writes TerminalOutcome + evidence",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository.record_outcome",
        evidence=(
            "record_outcome(owner, program_id, job_key, outcome, evidence): writes "
            "TerminalOutcome (DELIVERED|NO_OP|BLOCKED) and evidence tuple to CalyxProgramJob row; "
            "immutable record once set to TERMINAL; per-owner, per-job isolation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="outcome_capture_empirical_stats",
        area="outcome_capture",
        title="Empirical stats aggregation — _empirical_stats() outcome_counts per executor role",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._empirical_stats",
        evidence=(
            "_empirical_stats(jobs): outcome_counts Counter (DELIVERED|NO_OP|BLOCKED|PENDING); "
            "successful_terminal_count, descriptive_success_rate; "
            "success_rate_semantics: 'historical_observation_not_predictive_certainty'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="outcome_capture_receipt_coverage",
        area="outcome_capture",
        title="Receipt coverage tracking — _receipt_metadata() execution receipt per job",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._receipt_metadata",
        evidence=(
            "_receipt_metadata(job): payload.get('receipt_type') in ('execution', 'cancellation'); "
            "_empirical_stats(): receipt_coverage = receipt_count / len(jobs); "
            "receipt_coverage surface shows what fraction of jobs have confirmed execution receipts"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="outcome_capture_owner_scoped",
        area="outcome_capture",
        title="Owner-scoped experience capture — load_owner_capability_registry() per-owner isolation",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.load_owner_capability_registry",
        evidence=(
            "load_owner_capability_registry(db, owner): filters jobs by owner; "
            "project_capability_profiles(active_registry, jobs): per-owner empirical profiles; "
            "cross-owner experience is not mixed: each owner sees only their own ledger"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ REPLAY
    LedgerAuditCriterion(
        criterion_id="replay_persisted_patch",
        area="replay",
        title="Replayable patch evidence — PersistedPatchExecution SHA-256 before/after",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.persisted_patch_execution.PersistedPatchExecution",
        evidence=(
            "PersistedPatchExecution: sha256_before, sha256_after, patches, applied_at, verified; "
            "replay: same patch on same sha256_before always produces same sha256_after; "
            "get_completed(): retrieves durable result for replay verification"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="replay_event_continuation",
        area="replay",
        title="Event continuation replay — event_continuation.py stateful replay path",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation",
        evidence=(
            "event_continuation.py: stateful event replay; "
            "GovervedResearchExecutor: TERMINAL state is absorbing — replay returns same outcome; "
            "event continuation is idempotent for completed executor runs"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="replay_brain_capture_rollback",
        area="replay",
        title="Capture rollback as replay correction — BrainCandidateStore.rollback()",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.BrainCandidateStore.rollback",
        evidence=(
            "BrainCandidateStore.rollback(bundle_id): removes failed bundle and its records; "
            "enables re-capture after correction; "
            "BrainCaptureBundle.checksum(): verifies bundle integrity before promotion attempt"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ FAILURE
    LedgerAuditCriterion(
        criterion_id="failure_blocked_outcome_record",
        area="failure",
        title="Failure outcome recording — TerminalOutcome.BLOCKED captured in ledger",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_core.TerminalOutcome",
        evidence=(
            "TerminalOutcome.BLOCKED: explicit failure terminal state; "
            "record_outcome() writes BLOCKED with evidence (blocker description); "
            "_empirical_stats(): BLOCKED appears in outcome_counts for failure analysis"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="failure_governance_boundary",
        area="failure",
        title="Failure cannot bypass governance — historical_failure_cannot_bypass_governance",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.project_capability_profiles",
        evidence=(
            "authority_boundary: 'historical_failure_cannot_bypass_governance': True; "
            "'historical_success_cannot_raise_authority_ceiling': True; "
            "empirical learning is observational; it cannot change security boundaries"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="failure_research_github_feedback",
        area="failure",
        title="Research failure feedback — upsert_research_status_comment() failure disclosure",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.github_research_feedback.upsert_research_status_comment",
        evidence=(
            "upsert_research_status_comment(): posts failure state to GitHub issue; "
            "idempotent: same failure state produces same comment; "
            "failure status is visible to owner without requiring manual inspection"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVIDER
    LedgerAuditCriterion(
        criterion_id="provider_outcome_no_api_park",
        area="provider",
        title="Provider outcome — PARK_PROVIDER_REQUIRED recorded when NO-API mode active",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryAction",
        evidence=(
            "FactoryAction.PARK_PROVIDER_REQUIRED: returned when intent.provider_required=True "
            "and NO-API mode active; park action recorded in factory decision, "
            "not silently dropped; planning can route around parked tasks"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="provider_executor_key_tracking",
        area="provider",
        title="Executor key per job — _receipt_metadata() tracks executor_key in job payload",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._receipt_metadata",
        evidence=(
            "_receipt_metadata(job): executor_key = payload.get('executor_key'); "
            "_empirical_stats(): most_used_executor_keys tracked per role; "
            "provider outcome attributable to specific executor by key"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="provider_live_outcome_capture",
        area="provider",
        title="Live provider outcome capture — requires generative provider provisioning",
        status=LedgerAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.provider_runtime.runtime_provider_configuration",
        evidence=(
            "runtime_provider_configuration(): generative_ready=False in NO-API mode; "
            "live provider outcomes cannot be captured without active generative provider; "
            "provider outcome ledger entries only accumulate in provisioned environment"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: generative provider not provisioned; "
            "live provider outcome capture requires active model provider"
        ),
        next_action="Activate generative provider for live provider outcome accumulation in ledger",
    ),

    # ------------------------------------------------------------------ PLANNING
    LedgerAuditCriterion(
        criterion_id="planning_empirical_routing_feedback",
        area="planning",
        title="Empirical routing feedback — project_capability_profiles() descriptive routing context",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.project_capability_profiles",
        evidence=(
            "project_capability_profiles(): empirical field per executor role has "
            "outcome_counts, descriptive_success_rate for routing guidance; "
            "empirical_authority: 'descriptive_routing_context_only' (not normative planning)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="planning_approved_task_priority",
        area="planning",
        title="Priority planning feedback — approved_tasks.py priority-ordered reservoir",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "APPROVED_TASKS: 47+ tasks in stable priority order; priority field in ApprovedTask; "
            "autonomous recursive implementation selects next highest priority safe task; "
            "planning feedback is explicit in priority ordering, not learned from outcomes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    LedgerAuditCriterion(
        criterion_id="security_no_credential_in_ledger",
        area="security",
        title="No credential values in ledger — evidence tuple contains only status strings",
        status=LedgerAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository.record_outcome",
        evidence=(
            "record_outcome(evidence=tuple[str,...]): evidence is string tuple (status messages); "
            "CLAUDE.md: no credential value may be requested, printed, logged, copied, or committed; "
            "ledger payload contains outcome state descriptions, never credential values"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    LedgerAuditCriterion(
        criterion_id="security_ledger_read_only_promotion",
        area="security",
        title="Ledger read-only — empirical stats inform routing but cannot promote to authority",
        status=LedgerAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.capability_memory.project_capability_profiles",
        evidence=(
            "'empirical_metrics_do_not_expand_authority': True; "
            "'historical_success_cannot_restore_registration': True; "
            "promotion of empirical results to authority requires explicit owner decision"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before promoting any empirical pattern to authority",
    ),

    # ------------------------------------------------------------------ DURABLE
    LedgerAuditCriterion(
        criterion_id="durable_program_job_persistence",
        area="durable",
        title="Durable ledger persistence — CalyxProgramJob rows survive process restart",
        status=LedgerAuditStatus.BLOCKED,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository",
        evidence=(
            "PersistentProgramRepository uses SQLAlchemy Session requiring DATABASE_URL; "
            "without DATABASE_URL falls back to in-memory (not cross-restart durable); "
            "durable experience ledger requires DATABASE_URL provisioned in deployment"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL not provisioned in this execution environment; "
            "experience ledger records survive only in-process (in-memory mode)"
        ),
        next_action="Provision DATABASE_URL for durable experience ledger persistence in production",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class ExperienceLedgerAudit:
    """Machine-readable experience ledger audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[LedgerAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[LedgerAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[LedgerAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(LedgerAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(LedgerAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(LedgerAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(LedgerAuditStatus.OWNER_GATED))

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


def get_experience_ledger_audit() -> ExperienceLedgerAudit:
    """Return the current experience ledger audit. Pure function — no external calls."""
    return ExperienceLedgerAudit(criteria=list(LEDGER_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[LedgerAuditCriterion]:
    return [c for c in LEDGER_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[LedgerAuditCriterion]:
    return [c for c in LEDGER_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[LedgerAuditCriterion]:
    return get_criteria_by_status(LedgerAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in LEDGER_AUDIT_CRITERIA
        if c.next_action
    ]
