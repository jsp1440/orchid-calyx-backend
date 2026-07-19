from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MISSION_STATES = ("draft", "awaiting_approval", "approved", "queued", "running", "paused", "completed", "failed", "cancelled", "expired", "superseded", "blocked")
JOB_STATES = ("pending", "available", "claimed", "running", "succeeded", "retry_wait", "failed", "cancelled", "dead_lettered", "blocked", "skipped")

MISSION_TRANSITIONS = {
    "draft": {"awaiting_approval", "cancelled", "superseded"},
    "awaiting_approval": {"approved", "blocked", "cancelled"},
    "approved": {"queued", "paused", "cancelled", "expired", "superseded"},
    "queued": {"running", "paused", "completed", "failed", "cancelled", "blocked", "expired"},
    "running": {"queued", "completed", "failed", "paused", "cancelled", "blocked"},
    "paused": {"approved", "queued", "cancelled", "expired"},
    "failed": {"queued", "cancelled", "superseded"},
    "completed": {"superseded"},
    "cancelled": {"superseded"},
    "expired": {"superseded"},
    "superseded": set(),
    "blocked": {"superseded"},
}


@dataclass(frozen=True)
class MissionType:
    mission_type: str
    handler: str
    required_authorization: str = "owner_or_api_key"
    risk_level: str = "low"
    write_scope: str = "read_only"
    allowed_database_schemas: tuple[str, ...] = ()
    forbidden_database_schemas: tuple[str, ...] = ("oc_taxonomy",)
    timeout_seconds: int = 60
    retry_policy: dict[str, Any] = field(default_factory=lambda: {"maximum_attempts": 2, "retry_delay_seconds": 60})
    human_approval_required: bool = False
    dry_run_required: bool = False
    publication_authority_required: bool = False
    canonical_graph_writes_permitted: bool = False
    taxonomy_writes_prohibited: bool = True
    audit_requirements: tuple[str, ...] = ("mission_event", "job_attempt")

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_type": self.mission_type,
            "handler": self.handler,
            "input_schema": {},
            "output_schema": {},
            "required_authorization": self.required_authorization,
            "risk_level": self.risk_level,
            "write_scope": self.write_scope,
            "allowed_database_schemas": list(self.allowed_database_schemas),
            "forbidden_database_schemas": list(self.forbidden_database_schemas),
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy,
            "human_approval_required": self.human_approval_required,
            "dry_run_required": self.dry_run_required,
            "publication_authority_required": self.publication_authority_required,
            "canonical_graph_writes_permitted": self.canonical_graph_writes_permitted,
            "taxonomy_writes_prohibited": self.taxonomy_writes_prohibited,
            "audit_requirements": list(self.audit_requirements),
        }


MISSION_TYPES: dict[str, MissionType] = {
    "system_health_check": MissionType("system_health_check", "system_health_check", allowed_database_schemas=("oc_missions", "oc_graph")),
    "telemetry_snapshot": MissionType("telemetry_snapshot", "telemetry_snapshot", allowed_database_schemas=("oc_missions",)),
    "intake_batch_review": MissionType("intake_batch_review", "not_implemented_safe_block", risk_level="medium"),
    "semantic_extraction": MissionType("semantic_extraction", "not_implemented_safe_block", risk_level="medium", write_scope="semantic_review_only", allowed_database_schemas=("oc_semantic",)),
    "ontology_resolution": MissionType("ontology_resolution", "not_implemented_safe_block", risk_level="medium", write_scope="ontology_review_only", allowed_database_schemas=("oc_ontology",)),
    "evidence_readiness_evaluation": MissionType("evidence_readiness_evaluation", "not_implemented_safe_block", risk_level="medium", allowed_database_schemas=("oc_ontology",)),
    "publication_dry_run": MissionType("publication_dry_run", "not_implemented_safe_block", risk_level="medium", allowed_database_schemas=("oc_publication",), dry_run_required=True),
    "controlled_publication": MissionType("controlled_publication", "not_implemented_safe_block", risk_level="high", write_scope="controlled_publication_only", allowed_database_schemas=("oc_publication", "oc_graph"), human_approval_required=True, dry_run_required=True, publication_authority_required=True, canonical_graph_writes_permitted=True),
    "graph_integrity_audit": MissionType("graph_integrity_audit", "graph_integrity_audit", allowed_database_schemas=("oc_graph",)),
    "taxonomy_integrity_audit": MissionType("taxonomy_integrity_audit", "taxonomy_integrity_audit", allowed_database_schemas=("oc_taxonomy",)),
    "source_registry_refresh": MissionType("source_registry_refresh", "not_implemented_safe_block", risk_level="medium"),
    "literature_ingestion_review": MissionType("literature_ingestion_review", "not_implemented_safe_block", risk_level="medium"),
    "stale_record_review": MissionType("stale_record_review", "not_implemented_safe_block"),
    "failed_job_retry": MissionType("failed_job_retry", "not_implemented_safe_block", risk_level="medium"),
    "report_generation": MissionType("report_generation", "mission_control_status_report"),
}

SAFE_TEMPLATES = (
    {
        "template_key": "backend_health_audit",
        "title": "Backend Health Audit",
        "description": "Read backend/runtime/database health without mutating domain data.",
        "mission_type": "system_health_check",
        "default_priority": 80,
        "default_risk": "low",
        "default_inputs": {},
        "required_approvals": [],
        "allowed_actions": ["read_health", "read_runtime_telemetry", "count_graph_rows", "count_taxonomy_rows"],
        "prohibited_actions": ["taxonomy_write", "canonical_graph_publish", "external_api_call", "arbitrary_code"],
    },
    {
        "template_key": "knowledge_graph_integrity_audit",
        "title": "Knowledge Graph Integrity Audit",
        "description": "Read canonical graph counts and duplicate indicators.",
        "mission_type": "graph_integrity_audit",
        "default_priority": 70,
        "default_risk": "low",
        "default_inputs": {},
        "required_approvals": [],
        "allowed_actions": ["read_graph_counts"],
        "prohibited_actions": ["canonical_graph_publish", "taxonomy_write"],
    },
    {
        "template_key": "taxonomy_non_mutation_audit",
        "title": "Taxonomy Non-Mutation Audit",
        "description": "Read taxonomy counts to verify no mutation occurred.",
        "mission_type": "taxonomy_integrity_audit",
        "default_priority": 70,
        "default_risk": "low",
        "default_inputs": {},
        "required_approvals": [],
        "allowed_actions": ["read_taxonomy_counts"],
        "prohibited_actions": ["taxonomy_write"],
    },
    {
        "template_key": "mission_control_status_report",
        "title": "Mission Control Status Report",
        "description": "Generate a read-only status report from mission and runtime telemetry.",
        "mission_type": "report_generation",
        "default_priority": 60,
        "default_risk": "low",
        "default_inputs": {},
        "required_approvals": [],
        "allowed_actions": ["read_mission_telemetry"],
        "prohibited_actions": ["external_send", "arbitrary_code"],
    },
)


def validate_mission_transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in MISSION_TRANSITIONS.get(current, set()):
        raise ValueError(f"INVALID_MISSION_TRANSITION:{current}->{target}")
