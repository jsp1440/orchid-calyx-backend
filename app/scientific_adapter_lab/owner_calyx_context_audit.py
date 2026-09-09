"""Owner Calyx program context audit — Approved Task Priority 16.

Verifies Calyx can read bounded repository, CI, provider,
completion-graph, module, blocker, and owner-gate context.

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

SCHEMA_VERSION = "owner-calyx-context-audit/v1"
AUDIT_DATE = "2026-09-09"


class ContextAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class ContextAuditCriterion:
    """One measurable criterion in the owner Calyx program context audit."""

    criterion_id: str
    area: str        # repository | ci | provider | completion_graph | module | blocker | owner_gate
    title: str
    status: str      # ContextAuditStatus constant
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
# Canonical program context criteria
# ---------------------------------------------------------------------------

CONTEXT_AUDIT_CRITERIA: tuple[ContextAuditCriterion, ...] = (

    # ------------------------------------------------------------------ REPOSITORY
    ContextAuditCriterion(
        criterion_id="repository_approved_task_reservoir",
        area="repository",
        title="Bounded approved task reservoir — approved_tasks.py ordered priority list",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "approved_tasks.py: ApprovedTask namedtuple (key, category, priority, title, description); "
            "APPROVED_TASKS list 47+ tasks in strict priority order; "
            "read-only Python module, no live repository API call required"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="repository_branch_context",
        area="repository",
        title="Bounded branch context — designated dev branch per CLAUDE.md git instructions",
        status=ContextAuditStatus.READY,
        authoritative_module="CLAUDE.md",
        evidence=(
            "CLAUDE.md: branch development instructions and convergence posture; "
            "AGENTS.md: lane separation; session system prompt names target branch explicitly; "
            "git log read locally without external API call"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="repository_agent_operating_memory",
        area="repository",
        title="Durable agent operating memory — AGENT-OPERATING-MEMORY.md corrections",
        status=ContextAuditStatus.READY,
        authoritative_module="docs/AGENT-OPERATING-MEMORY.md",
        evidence=(
            "docs/AGENT-OPERATING-MEMORY.md: durable corrections from convergence failures; "
            "CLAUDE.md startup sequence: read this before editing; "
            "current repository truth outranks stale session memory"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CI
    ContextAuditCriterion(
        criterion_id="ci_required_checks",
        area="ci",
        title="CI required-check context — exact-head verification before integration",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate() requires validation_evidence.check_suite_passed=True; "
            "CLAUDE.md: checker must validate exact maker head SHA and required checks; "
            "review_eligibility.py: required check enumeration"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="ci_check_suite_status",
        area="ci",
        title="CI check-suite status reading — stale/skipped/cancelled rejection",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.review_eligibility",
        evidence=(
            "review_eligibility.py: required checks enumeration and exact-head match logic; "
            "CLAUDE.md Validation section: distinguish PR-introduced vs main-reproducible failures; "
            "no stale CI: checker validates exact head SHA"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="ci_live_github_check",
        area="ci",
        title="Live GitHub CI check-run context (mcp__github__actions_list)",
        status=ContextAuditStatus.BLOCKED,
        authoritative_module="mcp.github.actions_list",
        evidence=(
            "GitHub MCP tools mcp__github__actions_list and mcp__github__get_check_run "
            "are available but require outbound GitHub API network access; "
            "GitHub Actions CI state is checked at PR review time, not at audit-write time"
        ),
        gap_description=None,
        blocker_reason=(
            "Live CI state is a runtime read at PR review, not a static invariant; "
            "static audit cannot snapshot live check status without an external API call"
        ),
        next_action="Read live CI state via mcp__github__actions_list at PR review time",
    ),

    # ------------------------------------------------------------------ PROVIDER
    ContextAuditCriterion(
        criterion_id="provider_runtime_configuration",
        area="provider",
        title="Provider runtime configuration context — generative_ready flag, NO-API disclosure",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_conversation.provider_runtime.runtime_provider_configuration",
        evidence=(
            "runtime_provider_configuration() returns: selected, generative_ready (bool), "
            "missing_configuration, secrets_exposed=False; "
            "speak_status() surfaces provider block including generative flag"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="provider_no_api_park_action",
        area="provider",
        title="NO-API mode park action — PARK_PROVIDER_REQUIRED in FactoryAction",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryAction",
        evidence=(
            "FactoryAction.PARK_PROVIDER_REQUIRED: returned by evaluate_factory_gate when "
            "intent.provider_required=True and NO-API mode is detected; "
            "factory bridge routes to parked state, no generative spend occurs"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ COMPLETION_GRAPH
    ContextAuditCriterion(
        criterion_id="completion_graph_program_snapshot",
        area="completion_graph",
        title="Program snapshot — PersistentProgramRepository.snapshot() completion-graph read",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository.snapshot",
        evidence=(
            "PersistentProgramRepository.snapshot() returns full program state: "
            "job statuses, outcomes, dependencies, evidence; "
            "bounded to per-owner program_id; read-only graph traversal"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="completion_graph_job_statuses",
        area="completion_graph",
        title="Completion-graph job statuses — ProgramJobStatus enum bounded leaf tracking",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_core.ProgramJobStatus",
        evidence=(
            "ProgramJobStatus: WAITING | READY | RUNNING | TERMINAL | CANCELLED; "
            "ProgramStatus: DRAFT | RUNNING | PAUSED | COMPLETED | BLOCKED | CANCELLED; "
            "TerminalOutcome: DELIVERED | NO_OP | BLOCKED; dependencies tracked in ProgramJobSpec"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="completion_graph_dependency_ordering",
        area="completion_graph",
        title="Completion-graph dependency ordering — acyclicity enforcement before release",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository._assert_acyclic",
        evidence=(
            "_assert_acyclic() validates no cycles before program creation; "
            "release_ready_jobs() only releases jobs with all dependencies in SUCCESSFUL_DEPENDENCY_OUTCOMES; "
            "bounded execution: no job runs before dependencies resolve"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ MODULE
    ContextAuditCriterion(
        criterion_id="module_factory_policy_risk_gate",
        area="module",
        title="Factory policy risk gate — evaluate_factory_gate() context reader",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(intent, state, evidence) returns FactoryDecision; "
            "reads: RiskTier, CheckerVerdict, MissionStatus, NO-API mode, provider_required, "
            "exact_head_match, is_main_branch; routes to REQUIRE_CHECKER | AUTO_INTEGRATE | "
            "PREPARE_REPAIR | PARK_PROVIDER_REQUIRED | OWNER_GATE"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="module_scientific_adapter_lab",
        area="module",
        title="Scientific adapter lab module inventory — static audit surface for all capabilities",
        status=ContextAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab",
        evidence=(
            "scientific_adapter_lab/: taxonomy_readiness_audit (P10), calyx_runtime_truth_audit (P11), "
            "calyx_research_executor_audit (P12), canonical_scientific_reads_audit (P13), "
            "calyx_acceptance_mission_audit (P14), owner_calyx_mobile_audit (P15), "
            "owner_calyx_context_audit (P16 — this module); each is pure static, no external calls"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="module_agent_security_gateway",
        area="module",
        title="Agent Security Gateway — security boundary context for all executor calls",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.agent_security_gateway",
        evidence=(
            "agent_security_gateway.py: PROHIBITED_CAPABILITIES set, fail-closed blocking; "
            "common_security_boundary.py: shared security contract; "
            "CLAUDE.md: never weaken, bypass, or disable Agent Security Guard"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="module_deep_orchestrate_reservoir",
        area="module",
        title="Deep orchestrate reservoir — prioritized task reservoir beyond active lane",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate",
        evidence=(
            "deep_orchestrate.py: reservoir beyond active lane width; "
            "approved_tasks.py: 47+ tasks in stable priority order, stable keys, dedupe; "
            "CLAUDE.md: audit complete when bounded PR done, not just current task"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ BLOCKER
    ContextAuditCriterion(
        criterion_id="blocker_no_api_mode",
        area="blocker",
        title="NO-API mode blocker — PARK_PROVIDER_REQUIRED for all generative paths",
        status=ContextAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate: if intent.provider_required and no_api_mode: "
            "return FactoryDecision(action=PARK_PROVIDER_REQUIRED); "
            "all generative executor paths blocked; static audit paths are READY"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ContextAuditCriterion(
        criterion_id="blocker_database_url_missing",
        area="blocker",
        title="DATABASE_URL blocker — durable Postgres sessions blocked without env var",
        status=ContextAuditStatus.BLOCKED,
        authoritative_module="app.calyx_conversation.store.ConversationStore",
        evidence=(
            "ConversationStore.dsn reads DATABASE_URL env var; "
            "without it falls back to in-memory store (not durable across restarts); "
            "calyx_runtime_truth_audit P11 criterion persistence_postgres_unavailable is BLOCKED"
        ),
        gap_description=None,
        blocker_reason=(
            "DATABASE_URL not provisioned in this execution environment; "
            "durable conversation sessions unavailable in current context"
        ),
        next_action="Provision DATABASE_URL in deployment environment for durable session persistence",
    ),
    ContextAuditCriterion(
        criterion_id="blocker_live_external_adapters",
        area="blocker",
        title="Live external adapter blockers — GBIF, Europe PMC, elevation require network",
        status=ContextAuditStatus.BLOCKED,
        authoritative_module="app.scientific_adapter_lab.canonical_scientific_reads_audit",
        evidence=(
            "occurrence_gbif_live_adapter and elevation_live_provider are BLOCKED in "
            "canonical_scientific_reads_audit; literature executor BLOCKED in research_executor_audit; "
            "all live adapter paths fail-closed to UNAVAILABLE evidence state"
        ),
        gap_description=None,
        blocker_reason=(
            "Live external adapters (GBIF, Europe PMC, elevation providers) not provisioned; "
            "NO-API mode blocks generative providers; static audit modules are unaffected"
        ),
        next_action="Provision live adapter credentials in deployment environment when ready",
    ),

    # ------------------------------------------------------------------ OWNER_GATE
    ContextAuditCriterion(
        criterion_id="owner_gate_taxonomy_activation",
        area="owner_gate",
        title="Taxonomy activation owner gate — promotion_activation_blocked is OWNER_GATED",
        status=ContextAuditStatus.OWNER_GATED,
        authoritative_module="app.scientific_adapter_lab.taxonomy_readiness_audit",
        evidence=(
            "taxonomy_readiness_audit: promotion_activation_blocked is OWNER_GATED; "
            "rollback_production_authorization is OWNER_GATED; "
            "CLAUDE.md: never activate taxonomy without required owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before activating taxonomy in production",
    ),
    ContextAuditCriterion(
        criterion_id="owner_gate_evidence_publication",
        area="owner_gate",
        title="Evidence publication owner gate — no autonomous publication across all audit modules",
        status=ContextAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryAction",
        evidence=(
            "FactoryAction.OWNER_GATE: returned when _requires_owner(intent)=True; "
            "automatic_publication=False in speak_status; knowledge_graph_mutation=False; "
            "calyx_acceptance_mission_audit: security_acceptance_publication_gated is OWNER_GATED"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before publishing any evidence to canonical KG",
    ),
    ContextAuditCriterion(
        criterion_id="owner_gate_main_merge",
        area="owner_gate",
        title="Main branch merge gate — never merge to main without owner authorization",
        status=ContextAuditStatus.OWNER_GATED,
        authoritative_module="CLAUDE.md",
        evidence=(
            "CLAUDE.md: Do not merge/integrate to main or master without required owner authorization; "
            "factory_policy.evaluate_factory_gate: is_main_branch=True routes to OWNER_GATE; "
            "AGENTS.md: AUTO_INTEGRATE only for non-main integration branches"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before merging any branch to main",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class OwnerCalyxContextAudit:
    """Machine-readable owner Calyx program context audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[ContextAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[ContextAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[ContextAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(ContextAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(ContextAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(ContextAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(ContextAuditStatus.OWNER_GATED))

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


def get_owner_calyx_context_audit() -> OwnerCalyxContextAudit:
    """Return the current context audit. Pure function — no external calls."""
    return OwnerCalyxContextAudit(criteria=list(CONTEXT_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[ContextAuditCriterion]:
    return [c for c in CONTEXT_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[ContextAuditCriterion]:
    return [c for c in CONTEXT_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[ContextAuditCriterion]:
    return get_criteria_by_status(ContextAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in CONTEXT_AUDIT_CRITERIA
        if c.next_action
    ]
