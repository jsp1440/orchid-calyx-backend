"""Production deployment reconciliation audit — Approved Task Priority 35.

Identify serving platform, repository, branch, SHA, domain routing, deployed
artifact, and drift without changing production.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "deployment-reconciliation-audit/v1"
AUDIT_DATE = "2026-09-09"


class DeploymentReconciliationAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class DeploymentReconciliationCriterion:
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


DEPLOYMENT_RECONCILIATION_CRITERIA: tuple[DeploymentReconciliationCriterion, ...] = (

    # ------------------------------------------------------------------ COMMIT_DRIFT
    DeploymentReconciliationCriterion(
        criterion_id="commit_drift_detection",
        area="commit_drift",
        title="Deployed-commit drift detection — evaluate_deployed_commit_drift() identifies SHA mismatches",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.deployed_commit_drift.evaluate_deployed_commit_drift",
        evidence=(
            "evaluate_deployed_commit_drift(payload): "
            "deployed_commit_sha != expected_commit_sha → blockers: 'deployed_commit_drift'; "
            "main_commit_sha != expected_commit_sha → blockers: 'expected_commit_not_current_main'; "
            "aligned: not blockers (True only when deployed SHA matches expected)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="commit_drift_missing_sha",
        area="commit_drift",
        title="Missing SHA fields are blockers — blank deployed/main/expected SHA is detected",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.deployed_commit_drift.evaluate_deployed_commit_drift",
        evidence=(
            "evaluate_deployed_commit_drift(): "
            "not deployed → blockers: 'missing:deployed_commit_sha'; "
            "not main → blockers: 'missing:main_commit_sha'; "
            "not expected → blockers: 'missing:expected_commit_sha'; "
            "all three SHA fields must be present for aligned=True"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="commit_drift_no_production_action",
        area="commit_drift",
        title="No production action authorized — drift result never authorizes autonomous production changes",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.deployed_commit_drift.evaluate_deployed_commit_drift",
        evidence=(
            "evaluate_deployed_commit_drift(): production_action_authorized: False (always); "
            "drift detection is read-only — it reports alignment state but never authorizes "
            "any production mutation, rollback, or deployment action"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ARTIFACT_INTEGRITY
    DeploymentReconciliationCriterion(
        criterion_id="artifact_bundle_sha256",
        area="artifact_integrity",
        title="Artifact bundle SHA-256 — build_artifact_bundle() produces content-addressable artifact_hash",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.artifact_bundle.build_artifact_bundle",
        evidence=(
            "build_artifact_bundle(run_id, commit_sha, lane_results): "
            "canonical = json.dumps(payload, sort_keys=True); "
            "artifact_hash = hashlib.sha256(canonical.encode()).hexdigest(); "
            "artifact is content-addressable — any input change produces a different hash"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="artifact_bundle_commit_sha_minimum",
        area="artifact_integrity",
        title="Artifact commit SHA minimum length — len(commit_sha) < 7 is a blocker",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.artifact_bundle.build_artifact_bundle",
        evidence=(
            "build_artifact_bundle(): len(commit_sha) < 7 → blockers: 'COMMIT_SHA_INVALID'; "
            "aligns with EventKey minimum SHA requirement (7 characters); "
            "prevents trivial blank or truncated SHA from producing a valid artifact bundle"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="artifact_bundle_lanes_certified",
        area="artifact_integrity",
        title="Lane certification required — any uncertified lane blocks artifact bundle completion",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.artifact_bundle.build_artifact_bundle",
        evidence=(
            "build_artifact_bundle(): "
            "failed = sorted(name for name, result in lane_results.items() if result.get('certified') is not True); "
            "blockers += [f'{name}:NOT_CERTIFIED' for name in failed]; "
            "complete: not blockers — only fully-certified lane set yields complete=True"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="artifact_bundle_no_production_action",
        area="artifact_integrity",
        title="Artifact bundle never authorizes production — production_action_authorized always False",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.artifact_bundle.build_artifact_bundle",
        evidence=(
            "build_artifact_bundle(): production_action_authorized: False (always); "
            "artifact bundle is a certification record, not an authorization to deploy; "
            "production deployment still requires owner authorization path"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CERTIFICATION_SNAPSHOT
    DeploymentReconciliationCriterion(
        criterion_id="snapshot_snapshot_hash",
        area="certification_snapshot",
        title="Certification snapshot hash — build_certification_snapshot() produces canonical SHA-256 snapshot_hash",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.certification_snapshot.build_certification_snapshot",
        evidence=(
            "build_certification_snapshot(bundle, status): "
            "canonical = json.dumps(payload, sort_keys=True); "
            "snapshot_hash = sha256(canonical.encode()).hexdigest(); "
            "snapshot is content-addressable and canonical — deterministic for identical inputs"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="snapshot_certified_requires_both",
        area="certification_snapshot",
        title="Certification requires bundle + status — both must pass for certified=True",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.certification_snapshot.build_certification_snapshot",
        evidence=(
            "build_certification_snapshot(): "
            "bundle_complete = bundle.get('complete') or bundle.get('certified'); "
            "status_ready = status.get('status') == 'ready' or status.get('certification_ready'); "
            "certified = bundle_complete and status_ready and not blockers; "
            "all three conditions required — incomplete bundle or not-ready status blocks certification"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="snapshot_owner_authorization_required",
        area="certification_snapshot",
        title="Owner authorization required — certification snapshot never authorizes production",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.certification_snapshot.build_certification_snapshot",
        evidence=(
            "build_certification_snapshot(): "
            "owner_authorization_required: True (always); "
            "production_action_authorized: False (always); "
            "a certified snapshot is a necessary condition for deployment — not sufficient alone"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ READINESS_VIEW
    DeploymentReconciliationCriterion(
        criterion_id="readiness_view_assembly",
        area="readiness_view",
        title="Readiness view assembly — assemble_readiness_view() combines snapshot and live evidence",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.mission_control_readiness.assemble_readiness_view",
        evidence=(
            "assemble_readiness_view(snapshot, live_evidence): "
            "blockers = sorted(set(snapshot.get('blockers')) | set(live_evidence.get('blockers'))); "
            "ready = certified and evidence_accepted and not blockers; "
            "status: 'ready' | 'blocked'; "
            "union of snapshot and live-evidence blockers — neither alone is sufficient"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="readiness_view_no_production_action",
        area="readiness_view",
        title="Readiness view never authorizes production — owner_authorization_required=True always",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.mission_control_readiness.assemble_readiness_view",
        evidence=(
            "assemble_readiness_view(): "
            "owner_authorization_required: True (always); "
            "production_action_authorized: False (always); "
            "readiness view is a display artifact for owner decision — not an authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ROLLBACK_SAFETY
    DeploymentReconciliationCriterion(
        criterion_id="rollback_plan_required_fields",
        area="rollback_safety",
        title="Rollback plan validates required fields — previous SHA, restore command, DB backup, tested",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.rollback_readiness.validate_rollback_readiness",
        evidence=(
            "validate_rollback_readiness(plan): "
            "required = ('previous_commit_sha', 'restore_command', 'database_backup_id', 'tested'); "
            "blockers = [f'missing:{key}' for key in required if plan.get(key) in (None, '')]; "
            "all four fields must be present for rollback_ready=True"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="rollback_tested_required",
        area="rollback_safety",
        title="Rollback must be tested — untested rollback plans are blocked",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.rollback_readiness.validate_rollback_readiness",
        evidence=(
            "validate_rollback_readiness(): "
            "plan.get('tested') is not True → blockers: 'rollback_not_tested'; "
            "rollback_ready: not blockers — untested rollback cannot satisfy readiness check"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DeploymentReconciliationCriterion(
        criterion_id="rollback_no_production_action",
        area="rollback_safety",
        title="Rollback validation never authorizes production — production_action_authorized=False always",
        status=DeploymentReconciliationAuditStatus.READY,
        authoritative_module="runtime.calyx_certification.rollback_readiness.validate_rollback_readiness",
        evidence=(
            "validate_rollback_readiness(): production_action_authorized: False (always); "
            "rollback plan validation is read-only assessment — owner must authorize actual rollback execution"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PRODUCTION_GUARD
    DeploymentReconciliationCriterion(
        criterion_id="production_guard_no_autonomous_deploy",
        area="production_guard",
        title="No autonomous deployment — production_action_authorized=False across all reconciliation modules",
        status=DeploymentReconciliationAuditStatus.OWNER_GATED,
        authoritative_module="runtime.calyx_certification",
        evidence=(
            "deployed_commit_drift.py: production_action_authorized: False; "
            "artifact_bundle.py: production_action_authorized: False; "
            "certification_snapshot.py: production_action_authorized: False; "
            "mission_control_readiness.py: production_action_authorized: False; "
            "rollback_readiness.py: production_action_authorized: False; "
            "unanimous — no reconciliation module can autonomously authorize a production deployment"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must supply deployment authorization; all calyx_certification modules require owner decision",
    ),
    DeploymentReconciliationCriterion(
        criterion_id="production_guard_live_state_blocked",
        area="production_guard",
        title="Live serving state not readable — platform/domain/branch from production requires live access",
        status=DeploymentReconciliationAuditStatus.BLOCKED,
        authoritative_module="runtime.calyx_certification",
        evidence=(
            "Serving platform (Railway/Heroku/Fly/Render/GCP/AWS), deployed SHA, "
            "domain routing (orchid-calyx.example.com), and artifact digest "
            "are not statically accessible from repository code; "
            "calyx_certification modules model the certification protocol but do not "
            "provide live production introspection without platform API access"
        ),
        gap_description=None,
        blocker_reason="Live production state (deployed SHA, platform, domain, artifact digest) requires platform API or environment variable access not available in this context",
        next_action="Owner should provide deployed SHA, platform identity, and domain config to complete live reconciliation",
    ),
)


@dataclass
class DeploymentReconciliationAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[DeploymentReconciliationCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[DeploymentReconciliationCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[DeploymentReconciliationCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(DeploymentReconciliationAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(DeploymentReconciliationAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(DeploymentReconciliationAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(DeploymentReconciliationAuditStatus.OWNER_GATED))

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


def get_deployment_reconciliation_audit() -> DeploymentReconciliationAudit:
    return DeploymentReconciliationAudit(criteria=list(DEPLOYMENT_RECONCILIATION_CRITERIA))


def get_criteria_by_status(status: str) -> list[DeploymentReconciliationCriterion]:
    return [c for c in DEPLOYMENT_RECONCILIATION_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[DeploymentReconciliationCriterion]:
    return [c for c in DEPLOYMENT_RECONCILIATION_CRITERIA if c.area == area]


def get_gaps() -> list[DeploymentReconciliationCriterion]:
    return get_criteria_by_status(DeploymentReconciliationAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in DEPLOYMENT_RECONCILIATION_CRITERIA
        if c.next_action
    ]
