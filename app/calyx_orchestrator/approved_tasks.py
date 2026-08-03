from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedTask:
    job_type: str
    priority: int
    title: str
    request_text: str
    read_only: bool = True
    requires_owner_approval: bool = False


APPROVED_TASKS = (
    ApprovedTask("taxonomy_readiness", 10, "Audit taxonomy readiness", "Inspect taxonomy storage, staging, smoke certification, crosswalk, impact, promotion blockers, and rollback readiness."),
    ApprovedTask("knowledge_graph_quality", 20, "Audit Knowledge Graph quality", "Inspect coverage, contradictions, orphan nodes, unsupported edges, stale sources, and provenance gaps."),
    ApprovedTask("matrix_readiness", 30, "Audit Relationship Matrix", "Inspect evidence coverage, unavailable dimensions, neighborhood quality, and relationship-path explanations."),
    ApprovedTask("identification_readiness", 40, "Audit orchid identification", "Inspect observation coverage, candidate retrieval, conflicts, look-alikes, and expert-review pathways."),
    ApprovedTask("brain_readiness", 50, "Audit Brain reasoning", "Inspect evidence, Candidate Knowledge, contradiction, confidence, validation, review, and publication boundaries."),
    ApprovedTask("integration_readiness", 60, "Audit cross-repository integration", "Inspect Brain, backend, and frontend contract compatibility, route availability, and degraded states."),
    ApprovedTask("website_design_audit", 70, "Audit website design", "Inspect accessibility, UX, navigation, information architecture, and scientific visualization."),
    ApprovedTask("education_readiness", 80, "Audit education systems", "Inspect University models, curriculum alignment, lessons, assessments, and virtual-laboratory gaps."),
    ApprovedTask("harvester_readiness", 90, "Audit harvesters", "Inspect source freshness, failures, duplication, schedules, licensing, and schema drift."),
)

PROHIBITED_AUTONOMOUS_ACTIONS = {
    "merge_pull_request",
    "deploy_production",
    "run_production_migration",
    "promote_taxonomy",
    "publish_scientific_knowledge",
    "send_external_communication",
    "spend_money",
    "delete_canonical_data",
}


def task_profile() -> tuple[ApprovedTask, ...]:
    return tuple(sorted(APPROVED_TASKS, key=lambda task: (task.priority, task.job_type)))


def validate_task(task: ApprovedTask) -> None:
    if not task.read_only:
        raise ValueError("AUTONOMOUS_TASK_MUST_BE_READ_ONLY")
    if task.requires_owner_approval:
        raise ValueError("APPROVAL_TASK_CANNOT_RUN_UNATTENDED")
    if task.priority < 1:
        raise ValueError("INVALID_PRIORITY")


def task_provider_status() -> dict[str, object]:
    tasks = task_profile()
    for task in tasks:
        validate_task(task)
    return {
        "provider": "reviewed-static-v1",
        "mode": "preproduction",
        "task_count": len(tasks),
        "tasks": [task.__dict__ for task in tasks],
        "prohibited_actions": sorted(PROHIBITED_AUTONOMOUS_ACTIONS),
        "production_activation": False,
        "scientific_publication_authority": False,
    }
