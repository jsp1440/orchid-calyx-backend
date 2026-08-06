from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .product_agents import (
    PRODUCT_ROLE_REGISTRY,
    PROHIBITED_PRODUCT_ACTIONS,
    ProductAgentRole,
    product_role_snapshot,
)


@dataclass(frozen=True, slots=True)
class ProductJobTemplate:
    job_key: str
    role: ProductAgentRole
    title: str
    domain: str
    policy_gate: str
    required_outputs: tuple[str, ...]
    depends_on: tuple[str, ...] = ()


PRODUCT_JOB_TEMPLATES: tuple[ProductJobTemplate, ...] = (
    ProductJobTemplate(
        "conservatory_qr_readiness",
        ProductAgentRole.CONSERVATORY_ENGINEER,
        "Conservatory collection and QR workflow readiness",
        "conservatory",
        "owner_merge_and_deployment_required",
        ("collection_contract", "qr_workflow", "identity_rules", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "oasis_decision_support_readiness",
        ProductAgentRole.OASIS_ENGINEER,
        "OASIS care and greenhouse decision-support readiness",
        "oasis",
        "owner_merge_and_deployment_required",
        ("care_contract", "sensor_contract", "decision_rules", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "research_station_contract_readiness",
        ProductAgentRole.RESEARCH_STATION_ENGINEER,
        "Research Station project and notebook contract readiness",
        "research_station",
        "scientific_review_preserved",
        ("project_contract", "notebook_contract", "provenance", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "university_lab_contract_readiness",
        ProductAgentRole.UNIVERSITY_ENGINEER,
        "University lesson and laboratory contract readiness",
        "university",
        "owner_publication_required",
        ("curriculum_contract", "lab_contract", "assessment_rules", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "mission_control_product_visibility",
        ProductAgentRole.MISSION_CONTROL_ENGINEER,
        "Mission Control product-program visibility",
        "mission_control",
        "owner_merge_and_deployment_required",
        ("status_contract", "operator_controls", "accessibility", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "documentation_runbook_audit",
        ProductAgentRole.DOCUMENTATION_ENGINEER,
        "Documentation and runbook completeness audit",
        "documentation",
        "prepare_only",
        ("document_index", "runbook_coverage", "decision_log", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "operations_rollback_readiness",
        ProductAgentRole.OPERATIONS_ENGINEER,
        "Operations health and rollback-readiness audit",
        "operations",
        "production_deployment_prohibited",
        ("health_evidence", "telemetry_contract", "rollback_plan", "tests", "human_action"),
    ),
    ProductJobTemplate(
        "grant_draft_readiness",
        ProductAgentRole.GRANT_FUNDING_AGENT,
        "Grant and funding discovery and draft readiness audit",
        "grant_funding",
        "owner_submission_required",
        ("opportunity_identity", "eligibility", "deadline", "draft_artifact", "human_action"),
    ),
)

PRODUCT_PREREQUISITE_KEYS = tuple(item.job_key for item in PRODUCT_JOB_TEMPLATES)
PRODUCT_DIRECTOR_JOB = ProductJobTemplate(
    "product_director_report",
    ProductAgentRole.PRODUCT_DIRECTOR,
    "Product Director consolidated Phase 3 report",
    "product_governance",
    "owner_review_required",
    ("delivery_summary", "dependencies", "blockers", "deployment_state", "human_action"),
    depends_on=PRODUCT_PREREQUISITE_KEYS,
)


def build_product_program_fixture() -> dict[str, Any]:
    jobs = [*_snapshots(PRODUCT_JOB_TEMPLATES), *_snapshots((PRODUCT_DIRECTOR_JOB,))]
    return {
        "program_key": "phase_3_product_agents_demonstration",
        "title": "CALYX Phase 3 Product Agents Demonstration",
        "max_active_jobs": 6,
        "jobs": jobs,
        "dependencies": [
            {"upstream": key, "downstream": PRODUCT_DIRECTOR_JOB.job_key}
            for key in PRODUCT_PREREQUISITE_KEYS
        ],
        "release_rule": {
            "job_key": PRODUCT_DIRECTOR_JOB.job_key,
            "successful_outcomes": ["DELIVERED", "NO_OP"],
            "on_failed_prerequisite": "BLOCKED",
            "human_action_required": True,
        },
        "safety": {
            "automatic_merge": False,
            "production_deployment": False,
            "credential_use": False,
            "grant_submission": False,
            "binding_commitment": False,
            "scientific_publication": False,
            "taxonomy_activation": False,
            "production_graph_mutation": False,
        },
    }


def product_mission_control_snapshot() -> dict[str, Any]:
    fixture = build_product_program_fixture()
    return {
        "phase": 3,
        "status": "foundation_active",
        "roles": product_role_snapshot(),
        "role_count": len(PRODUCT_ROLE_REGISTRY),
        "job_templates": fixture["jobs"],
        "program": fixture,
        "policy_gates": sorted(PROHIBITED_PRODUCT_ACTIONS),
        "human_actions": [
            "Approve merge separately after review and required checks.",
            "Approve production deployment separately with rollback evidence.",
            "Approve any grant submission or binding commitment separately.",
            "Resolve blocked prerequisites before Product Director consolidation.",
        ],
    }


def _snapshots(templates: tuple[ProductJobTemplate, ...]) -> list[dict[str, Any]]:
    return [
        {
            "job_key": item.job_key,
            "role": item.role.value,
            "title": item.title,
            "domain": item.domain,
            "policy_gate": item.policy_gate,
            "required_outputs": list(item.required_outputs),
            "depends_on": list(item.depends_on),
            "status": "waiting" if item.depends_on else "ready",
        }
        for item in templates
    ]
