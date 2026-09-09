"""Meta-orchestrator audit — Approved Task Priority 19.

Inspects minimum-sufficient specialist planning, consequence classes,
authority gates, capability registry use, and human-gated high consequence.

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

SCHEMA_VERSION = "meta-orchestrator-audit/v1"
AUDIT_DATE = "2026-09-09"


class OrchestratorAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class OrchestratorAuditCriterion:
    """One measurable criterion in the meta-orchestrator audit."""

    criterion_id: str
    area: str        # planning | consequence | authority | capability | human_gate | security | reservoir
    title: str
    status: str      # OrchestratorAuditStatus constant
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
# Canonical meta-orchestrator criteria
# ---------------------------------------------------------------------------

ORCHESTRATOR_AUDIT_CRITERIA: tuple[OrchestratorAuditCriterion, ...] = (

    # ------------------------------------------------------------------ PLANNING
    OrchestratorAuditCriterion(
        criterion_id="planning_mission_spec",
        area="planning",
        title="Minimum-sufficient specialist planning — MissionSpec (kind, scientific, max_specialists)",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.specialist_service.MissionSpec",
        evidence=(
            "MissionSpec: kind (str), scientific (bool, default True), "
            "publication_candidate (bool, default False), max_specialists (int, default 4); "
            "plan_activation() caps specialists at max(1, min(max_specialists, 7)); "
            "minimum-sufficient: no more specialists than needed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="planning_specialist_cap",
        area="planning",
        title="Specialist count cap — max 7 specialists, owner-configurable default 4",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.specialist_service.plan_activation",
        evidence=(
            "plan_activation(): cap = max(1, min(max_specialists, 7)); "
            "SpecialistMission.max_specialists default 4; "
            "bounded execution: planning cannot spawn unbounded specialist chains"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="planning_reviewer_assignment",
        area="planning",
        title="Scientific reviewer assignment — reviewer required for scientific | publication_candidate",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.specialist_service.plan_activation",
        evidence=(
            "plan_activation(): 'reviewer': REVIEWER if scientific or publication_candidate else None; "
            "REVIEWER = 'scientific-reviewer'; "
            "publication candidates always get a reviewer; scientific missions do too"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="planning_program_dependency_graph",
        area="planning",
        title="Program dependency graph — acyclic job ordering for orchestrated missions",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.program_repository.PersistentProgramRepository._assert_acyclic",
        evidence=(
            "PersistentProgramRepository._assert_acyclic(): raises ValueError on cyclic dependencies; "
            "release_ready_jobs(): only releases when SUCCESSFUL_DEPENDENCY_OUTCOMES met; "
            "meta-orchestrator planning cannot create cycles"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CONSEQUENCE
    OrchestratorAuditCriterion(
        criterion_id="consequence_risk_classes",
        area="consequence",
        title="Consequence risk classes — low | medium | high in deep orchestrate reservoir",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.DeepTask",
        evidence=(
            "DeepTask.consequence_risk: 'low' | 'medium' | 'high'; "
            "deep_orchestrate.py: owner-gate isolation comment: "
            "'high-consequence tasks never auto-dispatch'; "
            "ReservoirTask serialization includes consequence_risk field"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="consequence_publication_candidate",
        area="consequence",
        title="Publication candidate consequence — owner_approval_required=True when pub candidate",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.specialist_service.plan_activation",
        evidence=(
            "plan_activation(): 'owner_approval_required': bool(publication_candidate); "
            "MissionSpec.publication_candidate=False by default; "
            "high-consequence publication path requires explicit opt-in and owner approval"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="consequence_factory_risk_tiers",
        area="consequence",
        title="Factory risk tier classes — LOW | MODERATE | HIGH | OWNER_GATED in factory_policy",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.RiskTier",
        evidence=(
            "RiskTier: LOW | MODERATE | HIGH | OWNER_GATED; "
            "evaluate_factory_gate(): routes HIGH → REQUIRE_CHECKER; "
            "OWNER_GATED → OWNER_GATE action; LOW+MODERATE non-main → AUTO_INTEGRATE eligible"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ AUTHORITY
    OrchestratorAuditCriterion(
        criterion_id="authority_ceiling_static",
        area="authority",
        title="Authority ceiling — static executor allowlist, empirical history cannot raise ceiling",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory._authority_ceiling",
        evidence=(
            "_authority_ceiling(): reads from registered executor dict; "
            "authority_boundary: 'empirical_metrics_do_not_expand_authority': True, "
            "'historical_success_cannot_raise_authority_ceiling': True; "
            "registry_authority: 'canonical_static_executor_allowlist'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="authority_gate_owner_gated",
        area="authority",
        title="Owner gate authority — OWNER_GATE action when _requires_owner() is True",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(intent): returns True for HIGH risk tier or main-branch target; "
            "evaluate_factory_gate(): if _requires_owner → FactoryAction.OWNER_GATE; "
            "authority gate is unconditional for owner-gated paths"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="authority_independent_checker",
        area="authority",
        title="Independent checker authority — checker must differ from maker for integration",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.ValidationEvidence.independent_checker",
        evidence=(
            "ValidationEvidence.independent_checker: bool property; "
            "evaluate_factory_gate(): REQUIRE_CHECKER until independent_checker=True + check_suite_passed; "
            "CLAUDE.md: maker cannot self-certify automatic integration"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CAPABILITY
    OrchestratorAuditCriterion(
        criterion_id="capability_registry_static",
        area="capability",
        title="Static capability registry — canonical executor allowlist via load_owner_capability_registry",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.load_owner_capability_registry",
        evidence=(
            "load_owner_capability_registry(): returns static executor authority + empirical history; "
            "project_capability_profiles(): SCHEMA_VERSION='calyx-capability-memory/1'; "
            "empirical_authority: 'descriptive_routing_context_only' (not normative)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="capability_empirical_routing_only",
        area="capability",
        title="Empirical history is routing context only — cannot expand authority ceiling",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.capability_memory.project_capability_profiles",
        evidence=(
            "project_capability_profiles(): 'authority_boundary': "
            "{'empirical_metrics_do_not_expand_authority': True, "
            "'historical_success_cannot_raise_authority_ceiling': True}; "
            "authority_ceiling for unregistered executor: 'NONE'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="capability_prohibited_set",
        area="capability",
        title="Prohibited capabilities set — PROHIBITED_CAPABILITIES in agent_security_gateway",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.agent_security_gateway.PROHIBITED_CAPABILITIES",
        evidence=(
            "PROHIBITED_CAPABILITIES: frozenset of disallowed capability identifiers; "
            "AgentSecurityGateway: fail-closed — any prohibited capability blocks execution; "
            "common_security_boundary.py: shared prohibition list"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ HUMAN_GATE
    OrchestratorAuditCriterion(
        criterion_id="human_gate_publication_approval",
        area="human_gate",
        title="Human gate for publication — SpecialistApproval.owner_approval_required",
        status=OrchestratorAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.specialist_models.SpecialistApproval",
        evidence=(
            "SpecialistApproval model: approval_key, mission_id, approved_by, approved_at; "
            "plan_activation(): owner_approval_required=True for publication_candidate; "
            "calyx_acceptance_mission_audit: security_acceptance_publication_gated is OWNER_GATED"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner approval for any publication_candidate specialist mission",
    ),
    OrchestratorAuditCriterion(
        criterion_id="human_gate_high_consequence_tasks",
        area="human_gate",
        title="Human gate for high-consequence tasks — never auto-dispatch consequence_risk=high",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate",
        evidence=(
            "deep_orchestrate.py: 'Owner-gate isolation: high-consequence tasks never auto-dispatch'; "
            "RiskTier.OWNER_GATED routes to FactoryAction.OWNER_GATE; "
            "taxonomy activation and production mutations are OWNER_GATED in all audit modules"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="human_gate_proposal_authorization",
        area="human_gate",
        title="Proposal authorization model — owner-authorized proposals before execution",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.proposal_authorization",
        evidence=(
            "proposal_authorization.py: proposals require explicit owner authorization; "
            "proposal_authorization_models.py: ProposalAuthorization status tracking; "
            "proposal_authorization_store.py: durable authorization records"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    OrchestratorAuditCriterion(
        criterion_id="security_agent_security_gateway",
        area="security",
        title="Agent Security Gateway — fail-closed blocking for all orchestrator calls",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.agent_security_gateway",
        evidence=(
            "AgentSecurityGateway: all capability checks fail-closed; "
            "PROHIBITED_CAPABILITIES blocks any prohibited operation; "
            "CLAUDE.md: never weaken, bypass, or disable Agent Security Guard"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    OrchestratorAuditCriterion(
        criterion_id="security_no_generative_spend",
        area="security",
        title="No generative spend in orchestrator — NO-API mode blocks generative paths",
        status=OrchestratorAuditStatus.BLOCKED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): PARK_PROVIDER_REQUIRED when provider_required=True "
            "and NO-API mode is active; meta-orchestrator static audit paths are unaffected; "
            "specialist planning is structural, not generative"
        ),
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live generative specialist execution requires provider not provisioned; "
            "specialist mission creation and planning structures are READY; execution is BLOCKED"
        ),
        next_action="Activate specialist execution when generative provider is provisioned",
    ),

    # ------------------------------------------------------------------ RESERVOIR
    OrchestratorAuditCriterion(
        criterion_id="reservoir_deep_orchestrate",
        area="reservoir",
        title="Deep orchestrate reservoir — prioritized task reservoir beyond active lane",
        status=OrchestratorAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate",
        evidence=(
            "deep_orchestrate.py: DeepTask with consequence_risk, state (QUEUED|RUNNING|BLOCKED); "
            "47+ tasks in approved_tasks.py as reservoir; "
            "stable keys, dedupe, stable priority order; no idle lanes"
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
class MetaOrchestratorAudit:
    """Machine-readable meta-orchestrator audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[OrchestratorAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[OrchestratorAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[OrchestratorAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(OrchestratorAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(OrchestratorAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(OrchestratorAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(OrchestratorAuditStatus.OWNER_GATED))

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


def get_meta_orchestrator_audit() -> MetaOrchestratorAudit:
    """Return the current meta-orchestrator audit. Pure function — no external calls."""
    return MetaOrchestratorAudit(criteria=list(ORCHESTRATOR_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[OrchestratorAuditCriterion]:
    return [c for c in ORCHESTRATOR_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[OrchestratorAuditCriterion]:
    return [c for c in ORCHESTRATOR_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[OrchestratorAuditCriterion]:
    return get_criteria_by_status(OrchestratorAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in ORCHESTRATOR_AUDIT_CRITERIA
        if c.next_action
    ]
