"""Capability registry audit — Approved Task Priority 23.

Verifies canonical capabilities, roles, provider requirements, authority,
costs, health, and endpoint bindings.

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

SCHEMA_VERSION = "capability-registry-audit/v1"
AUDIT_DATE = "2026-09-09"


class CapabilityRegistryAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class CapabilityRegistryAuditCriterion:
    """One measurable criterion in the capability registry audit."""

    criterion_id: str
    area: str        # roles | authority | provider | health | endpoint | security | empirical
    title: str
    status: str      # CapabilityRegistryAuditStatus constant
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
# Canonical capability registry criteria
# ---------------------------------------------------------------------------

CAPABILITY_REGISTRY_CRITERIA: tuple[CapabilityRegistryAuditCriterion, ...] = (

    # ------------------------------------------------------------------ ROLES
    CapabilityRegistryAuditCriterion(
        criterion_id="roles_canonical_allowlist",
        area="roles",
        title="Canonical role allowlist — AuthoritativeExecutorRegistry holds the bounded role set",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.AuthoritativeExecutorRegistry",
        evidence=(
            "AuthoritativeExecutorRegistry: bounded set of role_key registrations; "
            "eligible_role_keys: frozenset of allowed roles; "
            "require_authoritative() rejects unknown or external-side-effects roles"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="roles_registered_executor_dataclass",
        area="roles",
        title="RegisteredExecutor dataclass — role_key, executor, external_side_effects, workspace_mutation, repository_code_execution",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.RegisteredExecutor",
        evidence=(
            "RegisteredExecutor(frozen=True, slots=True): role_key, executor, "
            "external_side_effects, workspace_mutation, repository_code_execution; "
            "all flag fields default False — permissions must be explicitly granted, not assumed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="roles_known_registered_roles",
        area="roles",
        title="Known registered roles — autonomy_probe, repository_evidence, isolated_patch, static_validation",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry",
        evidence=(
            "AuthoritativeExecutorRegistry.__init__(): registers "
            "AUTONOMY_PROBE_ROLE, REPOSITORY_EVIDENCE_ROLE, ISOLATED_PATCH_ROLE, STATIC_VALIDATION_ROLE; "
            "no open-ended role registration at runtime; allowlist is compile-time bounded"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ AUTHORITY
    CapabilityRegistryAuditCriterion(
        criterion_id="authority_ceiling_static",
        area="authority",
        title="Authority ceiling static — computed from executor flags, not empirical performance",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._authority_ceiling",
        evidence=(
            "_authority_ceiling(): returns READ_ONLY | WORKSPACE | REPOSITORY | FULL based on "
            "executor.external_side_effects, repository_code_execution, workspace_mutation flags; "
            "empirical metrics do NOT expand authority ceiling"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="authority_ceiling_none_for_unregistered",
        area="authority",
        title="Unregistered roles get authority_ceiling=NONE, not a default grant",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.project_capability_profiles",
        evidence=(
            "project_capability_profiles(): historical_unregistered_role path sets "
            "authority_ceiling: 'NONE'; registration_state: 'historical_unregistered_role'; "
            "empirical history of an unregistered role cannot bootstrap authority"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="authority_empirical_cannot_raise",
        area="authority",
        title="Empirical success cannot raise authority ceiling — invariant enforced in output",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory",
        evidence=(
            "authority_boundary: {'empirical_metrics_do_not_expand_authority': True, "
            "'historical_success_cannot_raise_authority_ceiling': True}; "
            "hardcoded invariant present in both registered and unregistered profile branches"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="authority_no_external_side_effects",
        area="authority",
        title="External side effects forbidden — require_authoritative() rejects them",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.AuthoritativeExecutorRegistry",
        evidence=(
            "require_authoritative(): raises ValueError if registered.external_side_effects; "
            "all registered executors have external_side_effects=False; "
            "OWNER_GATE in factory_policy for changes_scientific_authority"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PROVIDER
    CapabilityRegistryAuditCriterion(
        criterion_id="provider_no_api_park",
        area="provider",
        title="NO-API provider work parked — PARK_PROVIDER_REQUIRED FactoryAction",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryAction",
        evidence=(
            "FactoryAction.PARK_PROVIDER_REQUIRED: action returned when provider_required=True and no_api_mode=True; "
            "WorkIntent.provider_required flag present; "
            "factory gate: 'NO_API_PROVIDER_WORK_PARKED' reason in FactoryDecision"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="provider_work_intent_flag",
        area="provider",
        title="WorkIntent.provider_required flag — gates all live-API capability dispatches",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.WorkIntent",
        evidence=(
            "WorkIntent(frozen=True): provider_required=False default; "
            "must be set True for any dispatch requiring live model or external API; "
            "factory_policy evaluates this flag before any provider call"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="provider_live_capability_health",
        area="provider",
        title="Live capability health check — requires external provider, BLOCKED in NO-API mode",
        status=CapabilityRegistryAuditStatus.BLOCKED,
        authoritative_module="app.calyx_orchestrator.factory_policy",
        evidence=(
            "Live provider health checks not available in NO-API execution mode; "
            "all model-API-dependent capabilities return PARK_PROVIDER_REQUIRED; "
            "health status is static/inferred from registration, not live-pinged"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode active — live provider health polling blocked; "
            "WorkIntent.provider_required=True would park immediately"
        ),
        next_action="Lift NO-API constraint to activate live provider health checks",
    ),

    # ------------------------------------------------------------------ HEALTH
    CapabilityRegistryAuditCriterion(
        criterion_id="health_registry_status_dict",
        area="health",
        title="Registry status dict — authoritative_roles, executors, flags per executor",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.AuthoritativeExecutorRegistry",
        evidence=(
            "registry.status(): {'authoritative_roles': sorted list, "
            "'sandboxed_repository_code_execution_authorized': False, "
            "'executors': [{role_key, executor_key, external_side_effects, workspace_mutation, "
            "repository_code_execution}]}"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="health_capability_profile_registry_authority",
        area="health",
        title="Capability profile registry authority — registry_authority annotated as canonical_static_executor_allowlist",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.project_capability_profiles",
        evidence=(
            "project_capability_profiles(): 'registry_authority': 'canonical_static_executor_allowlist'; "
            "'empirical_authority': 'descriptive_routing_context_only'; "
            "authority labels explicitly separate canonical registry from empirical observation"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ENDPOINT
    CapabilityRegistryAuditCriterion(
        criterion_id="endpoint_executor_key",
        area="endpoint",
        title="Executor key — each RegisteredExecutor exposes executor_key for receipt binding",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.RegisteredExecutor",
        evidence=(
            "RegisteredExecutor: executor.executor_key included in status() output per executor; "
            "executor_key used in ExecutionReceipt for provenance binding; "
            "_receipt_metadata(): extracts executor_key from CalyxProgramJob payload"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="endpoint_role_profiles_per_owner",
        area="endpoint",
        title="Per-owner capability profiles — load_owner_capability_registry isolates by owner",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.load_owner_capability_registry",
        evidence=(
            "load_owner_capability_registry(): queries CalyxProgramJob by owner_id; "
            "project_capability_profiles() called with owner-scoped jobs; "
            "cross-owner capability leakage prevented at query boundary"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    CapabilityRegistryAuditCriterion(
        criterion_id="security_no_open_registration",
        area="security",
        title="No open registration — runtime role additions not possible without code change",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.executor_registry.AuthoritativeExecutorRegistry",
        evidence=(
            "AuthoritativeExecutorRegistry.__init__(): roles set at object construction time; "
            "no public add_executor() method; no dynamic role injection at runtime; "
            "allowlist is frozen after initialization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="security_owner_gate_scientific_authority",
        area="security",
        title="Scientific authority changes owner-gated — changes_scientific_authority requires OWNER_GATE",
        status=CapabilityRegistryAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): _requires_owner() returns True for changes_scientific_authority=True; "
            "OWNER_GATE action returned before any other check; "
            "scientific capability authority changes cannot be auto-integrated"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any scientific authority expansion",
    ),

    # ------------------------------------------------------------------ EMPIRICAL
    CapabilityRegistryAuditCriterion(
        criterion_id="empirical_stats_outcome_counts",
        area="empirical",
        title="Empirical outcome counts — Counter of terminal outcomes per role, descriptive only",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._empirical_stats",
        evidence=(
            "_empirical_stats(): outcome_counts Counter per role_key; "
            "descriptive_success_rate: 'historical_observation_not_predictive_certainty'; "
            "receipt_coverage: observed_executor_keys / jobs; used for routing context only"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    CapabilityRegistryAuditCriterion(
        criterion_id="empirical_descriptive_routing_context",
        area="empirical",
        title="Empirical authority is descriptive only — cannot influence canonical authority ceiling",
        status=CapabilityRegistryAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory",
        evidence=(
            "empirical_authority: 'descriptive_routing_context_only'; "
            "empirical_metrics_do_not_expand_authority=True in authority_boundary; "
            "historical_success_cannot_raise_authority_ceiling=True; "
            "empirical data is separate from and subordinate to canonical registry authority"
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
class CapabilityRegistryAudit:
    """Machine-readable capability registry audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[CapabilityRegistryAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[CapabilityRegistryAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[CapabilityRegistryAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(CapabilityRegistryAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(CapabilityRegistryAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(CapabilityRegistryAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(CapabilityRegistryAuditStatus.OWNER_GATED))

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


def get_capability_registry_audit() -> CapabilityRegistryAudit:
    """Return the current capability registry audit. Pure function — no external calls."""
    return CapabilityRegistryAudit(criteria=list(CAPABILITY_REGISTRY_CRITERIA))


def get_criteria_by_status(status: str) -> list[CapabilityRegistryAuditCriterion]:
    return [c for c in CAPABILITY_REGISTRY_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[CapabilityRegistryAuditCriterion]:
    return [c for c in CAPABILITY_REGISTRY_CRITERIA if c.area == area]


def get_gaps() -> list[CapabilityRegistryAuditCriterion]:
    return get_criteria_by_status(CapabilityRegistryAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in CAPABILITY_REGISTRY_CRITERIA
        if c.next_action
    ]
