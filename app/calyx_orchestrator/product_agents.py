from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProductAgentRole(StrEnum):
    CONSERVATORY_ENGINEER = "conservatory_engineer"
    OASIS_ENGINEER = "oasis_engineer"
    RESEARCH_STATION_ENGINEER = "research_station_engineer"
    UNIVERSITY_ENGINEER = "university_engineer"
    MISSION_CONTROL_ENGINEER = "mission_control_engineer"
    DOCUMENTATION_ENGINEER = "documentation_engineer"
    OPERATIONS_ENGINEER = "operations_engineer"
    GRANT_FUNDING_AGENT = "grant_funding_agent"
    PRODUCT_DIRECTOR = "product_director"


class ProductPolicyClass(StrEnum):
    PREPARE_ONLY = "prepare_only"
    STAGING_ONLY = "staging_only"
    REVIEW_REQUIRED = "review_required"
    OWNER_ONLY = "owner_only"


PROHIBITED_PRODUCT_ACTIONS = frozenset(
    {
        "automatic_merge",
        "production_deployment",
        "use_credentials_without_approval",
        "store_secrets",
        "submit_grant",
        "make_binding_commitment",
        "publish_scientific_knowledge",
        "activate_taxonomy",
        "mutate_production_graph",
        "expose_private_chain_of_thought",
    }
)


@dataclass(frozen=True, slots=True)
class ProductRoleSpec:
    role: ProductAgentRole
    title: str
    mission: str
    policy_class: ProductPolicyClass
    required_evidence: tuple[str, ...]
    prohibited_actions: frozenset[str] = PROHIBITED_PRODUCT_ACTIONS
    requires_human_approval: bool = True


PRODUCT_ROLE_REGISTRY: dict[ProductAgentRole, ProductRoleSpec] = {
    ProductAgentRole.CONSERVATORY_ENGINEER: ProductRoleSpec(
        ProductAgentRole.CONSERVATORY_ENGINEER,
        "Conservatory Engineer",
        "Advance collection records, accessioning, labels, QR codes, locations, events, images, and plant dossiers.",
        ProductPolicyClass.STAGING_ONLY,
        ("collection_contract", "qr_workflow", "identity_rules", "tests", "human_action"),
    ),
    ProductAgentRole.OASIS_ENGINEER: ProductRoleSpec(
        ProductAgentRole.OASIS_ENGINEER,
        "OASIS Engineer",
        "Advance culture observations, greenhouse data, care schedules, alerts, and grower decision support.",
        ProductPolicyClass.STAGING_ONLY,
        ("care_contract", "sensor_contract", "decision_rules", "tests", "human_action"),
    ),
    ProductAgentRole.RESEARCH_STATION_ENGINEER: ProductRoleSpec(
        ProductAgentRole.RESEARCH_STATION_ENGINEER,
        "Research Station Engineer",
        "Advance projects, notebooks, datasets, collaboration, reproducible analyses, and exports.",
        ProductPolicyClass.STAGING_ONLY,
        ("project_contract", "notebook_contract", "provenance", "tests", "human_action"),
    ),
    ProductAgentRole.UNIVERSITY_ENGINEER: ProductRoleSpec(
        ProductAgentRole.UNIVERSITY_ENGINEER,
        "University Engineer",
        "Advance curricula, lessons, laboratories, assessments, and learner progress.",
        ProductPolicyClass.PREPARE_ONLY,
        ("curriculum_contract", "lab_contract", "assessment_rules", "tests", "human_action"),
    ),
    ProductAgentRole.MISSION_CONTROL_ENGINEER: ProductRoleSpec(
        ProductAgentRole.MISSION_CONTROL_ENGINEER,
        "Mission Control Engineer",
        "Expose governed queues, dependencies, approvals, failures, evidence, and operator controls.",
        ProductPolicyClass.STAGING_ONLY,
        ("status_contract", "operator_controls", "accessibility", "tests", "human_action"),
    ),
    ProductAgentRole.DOCUMENTATION_ENGINEER: ProductRoleSpec(
        ProductAgentRole.DOCUMENTATION_ENGINEER,
        "Documentation Engineer",
        "Maintain architecture records, API documentation, runbooks, user instructions, and decision logs.",
        ProductPolicyClass.PREPARE_ONLY,
        ("document_index", "runbook_coverage", "decision_log", "tests", "human_action"),
    ),
    ProductAgentRole.OPERATIONS_ENGINEER: ProductRoleSpec(
        ProductAgentRole.OPERATIONS_ENGINEER,
        "Operations Engineer",
        "Prepare production health, scheduled-worker, telemetry, incident, and rollback evidence without deploying.",
        ProductPolicyClass.REVIEW_REQUIRED,
        ("health_evidence", "telemetry_contract", "rollback_plan", "tests", "human_action"),
    ),
    ProductAgentRole.GRANT_FUNDING_AGENT: ProductRoleSpec(
        ProductAgentRole.GRANT_FUNDING_AGENT,
        "Grant and Funding Agent",
        "Discover funding, assess eligibility and deadlines, and prepare evidence-backed drafts without submission.",
        ProductPolicyClass.OWNER_ONLY,
        ("opportunity_identity", "eligibility", "deadline", "draft_artifact", "human_action"),
    ),
    ProductAgentRole.PRODUCT_DIRECTOR: ProductRoleSpec(
        ProductAgentRole.PRODUCT_DIRECTOR,
        "Product Director",
        "Consolidate product delivery evidence, dependencies, blockers, deployment gates, and exact owner decisions.",
        ProductPolicyClass.REVIEW_REQUIRED,
        ("delivery_summary", "dependencies", "blockers", "deployment_state", "human_action"),
    ),
}


@dataclass(frozen=True, slots=True)
class ProductResult:
    role: ProductAgentRole
    evidence: dict[str, Any]
    dependencies: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    deployment_state: str = "not_requested"
    requested_action: str | None = None

    def validate(self) -> None:
        spec = PRODUCT_ROLE_REGISTRY[self.role]
        missing = [key for key in spec.required_evidence if key not in self.evidence]
        if missing:
            raise ValueError(f"REQUIRED_PRODUCT_EVIDENCE_MISSING:{','.join(sorted(missing))}")
        if self.requested_action in PROHIBITED_PRODUCT_ACTIONS:
            raise PermissionError("PRODUCT_ACTION_PROHIBITED")
        if self.deployment_state not in {"not_requested", "blocked", "review_required", "ready_for_owner_review"}:
            raise ValueError("DEPLOYMENT_STATE_INVALID")


def product_role_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "role": role.value,
            "title": spec.title,
            "mission": spec.mission,
            "policy_class": spec.policy_class.value,
            "required_evidence": list(spec.required_evidence),
            "prohibited_actions": sorted(spec.prohibited_actions),
            "requires_human_approval": spec.requires_human_approval,
        }
        for role, spec in PRODUCT_ROLE_REGISTRY.items()
    ]
