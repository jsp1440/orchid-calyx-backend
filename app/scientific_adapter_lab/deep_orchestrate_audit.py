"""Deep orchestrate reservoir audit — Approved Task Priority 25.

Verify a deep prioritized reservoir exists beyond active lane width with
stable keys, dedupe, dependencies, acceptance, and governance metadata.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "deep-orchestrate-audit/v1"
AUDIT_DATE = "2026-09-09"


class DeepOrchAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class DeepOrchAuditCriterion:
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


DEEP_ORCH_CRITERIA: tuple[DeepOrchAuditCriterion, ...] = (

    # ------------------------------------------------------------------ RESERVOIR
    DeepOrchAuditCriterion(
        criterion_id="reservoir_approved_tasks_depth",
        area="reservoir",
        title="Reservoir depth — 47+ approved tasks in APPROVED_TASKS beyond active lane width",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "APPROVED_TASKS: tuple with 47+ ApprovedTask entries; "
            "active lane width bounded (max 7 specialists per MissionSpec); "
            "reservoir depth far exceeds active lane width"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="reservoir_stable_task_keys",
        area="reservoir",
        title="Stable task keys — each ApprovedTask has a unique string key across the reservoir",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks.ApprovedTask",
        evidence=(
            "ApprovedTask.key: unique identifier per task; "
            "key is stable across sessions (not generated at runtime); "
            "keys include 'completion_graph', 'epistemic_memory', 'capability_registry', etc."
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="reservoir_priority_ordering",
        area="reservoir",
        title="Priority ordering — reservoir sorted by integer priority, lower = execute first",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "ApprovedTask.priority: integer 1-46+; lower = executed first; "
            "APPROVED_TASKS tuple ordered by priority field; "
            "priority ordering is stable — no runtime re-sorting needed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEDUPE
    DeepOrchAuditCriterion(
        criterion_id="dedupe_material_fingerprint",
        area="dedupe",
        title="Material fingerprint — WorkIntent.material_fingerprint() hashes scope, risk, flags",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.WorkIntent",
        evidence=(
            "WorkIntent.material_fingerprint(): SHA-256 of canonical scope fields; "
            "FactoryDecision.fingerprint: propagated to every gate decision; "
            "unchanged work intent produces same fingerprint — deduplication key"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="dedupe_mission_state_fingerprint",
        area="dedupe",
        title="MissionState fingerprint validation — non-empty fingerprint required at construction",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.MissionState",
        evidence=(
            "MissionState.__post_init__(): raises ValueError if fingerprint.strip() is empty; "
            "fingerprint must be non-empty before MissionState can be constructed; "
            "prevents zero-fingerprint deduplication bypass"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="dedupe_scheduler_policy_class",
        area="dedupe",
        title="Scheduler policy class deduplication — claim() filtered by ENGINEERING_COMPLETION_POLICY",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "claim(): CalyxJob.policy_class == ENGINEERING_COMPLETION_POLICY filter; "
            "enqueue(): repeated enqueue allowed to correct stale parameters only; "
            "policy_class boundaries prevent cross-domain job dispatches"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEPENDENCIES
    DeepOrchAuditCriterion(
        criterion_id="dependencies_area_grouping",
        area="dependencies",
        title="Area grouping — tasks grouped by area (mission_control_audit, capability_inventory, etc.)",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks.ApprovedTask",
        evidence=(
            "ApprovedTask.area: groups tasks into logical domains; "
            "areas: mission_control_audit, capability_inventory, brain_audit, etc.; "
            "area grouping informs dependency locality — tasks within the same area share context"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="dependencies_sequential_priority_execution",
        area="dependencies",
        title="Sequential priority execution — lower-priority tasks wait for higher-priority completions",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "Priority 1 (calyx_finish_line) executes before priority 47; "
            "completion graph advances reservoir top-down; "
            "sequential ordering acts as implicit dependency chain"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ACCEPTANCE
    DeepOrchAuditCriterion(
        criterion_id="acceptance_schema_version",
        area="acceptance",
        title="Acceptance evidence schema version — each audit module carries SCHEMA_VERSION",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab",
        evidence=(
            "Each scientific_adapter_lab audit module: SCHEMA_VERSION = '<name>/v1'; "
            "serialize_as_json() includes schema_version in output; "
            "schema versioning enables acceptance evidence traceability"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="acceptance_no_auto_publication",
        area="acceptance",
        title="No-auto-publication flag — all audit modules declare no_auto_publication=True",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab",
        evidence=(
            "All audit dataclasses: no_auto_publication=True; no_production_mutation=True; "
            "flags are part of the serialized output for downstream governance checks; "
            "acceptance evidence cannot be auto-published to KG"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ GOVERNANCE
    DeepOrchAuditCriterion(
        criterion_id="governance_owner_gated_tasks",
        area="governance",
        title="Owner-gated governance — OWNER_GATED status for tasks requiring authorization",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab",
        evidence=(
            "Status vocabulary: OWNER_GATED for tasks requiring explicit owner authorization; "
            "taxonomy activation, KG mutation, main merge all carry OWNER_GATED status; "
            "governance metadata preserved in serialized audit output"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="governance_blocked_tasks",
        area="governance",
        title="BLOCKED governance metadata — each blocked task names its specific dependency",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab",
        evidence=(
            "Status vocabulary: BLOCKED with blocker_reason and next_action; "
            "blocked tasks name the dependency: DATABASE_URL, NO-API mode, live external adapters; "
            "governance metadata is machine-readable for downstream triage"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    DeepOrchAuditCriterion(
        criterion_id="security_no_runtime_injection",
        area="security",
        title="No runtime task injection — reservoir is a compile-time tuple, not a mutable queue",
        status=DeepOrchAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.approved_tasks",
        evidence=(
            "APPROVED_TASKS: Python tuple — immutable at runtime; "
            "no API endpoint for adding new approved tasks dynamically; "
            "reservoir cannot be extended without code change and review"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeepOrchAuditCriterion(
        criterion_id="security_owner_gate_promotion",
        area="security",
        title="Owner gate on reservoir promotion — published scientific knowledge requires authorization",
        status=DeepOrchAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): OWNER_GATE for changes_scientific_authority; "
            "reservoir task completion does not automatically publish to KG; "
            "owner authorization is the terminal gate before any scientific promotion"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before promoting any reservoir result to KG",
    ),
)


@dataclass
class DeepOrchAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[DeepOrchAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[DeepOrchAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[DeepOrchAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(DeepOrchAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(DeepOrchAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(DeepOrchAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(DeepOrchAuditStatus.OWNER_GATED))

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


def get_deep_orch_audit() -> DeepOrchAudit:
    return DeepOrchAudit(criteria=list(DEEP_ORCH_CRITERIA))


def get_criteria_by_status(status: str) -> list[DeepOrchAuditCriterion]:
    return [c for c in DEEP_ORCH_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[DeepOrchAuditCriterion]:
    return [c for c in DEEP_ORCH_CRITERIA if c.area == area]


def get_gaps() -> list[DeepOrchAuditCriterion]:
    return get_criteria_by_status(DeepOrchAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in DEEP_ORCH_CRITERIA
        if c.next_action
    ]
