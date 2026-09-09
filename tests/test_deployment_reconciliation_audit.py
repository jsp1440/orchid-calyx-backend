"""Tests for production deployment reconciliation audit (Approved Task Priority 35)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.deployment_reconciliation_audit import (
    DEPLOYMENT_RECONCILIATION_CRITERIA,
    DeploymentReconciliationAuditStatus,
    get_deployment_reconciliation_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_deployment_reconciliation_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "deployment-reconciliation-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(DEPLOYMENT_RECONCILIATION_CRITERIA) >= 14


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(DEPLOYMENT_RECONCILIATION_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_audit_has_owner_gated_items():
    assert _AUDIT.owner_gated_count() >= 1


def test_live_state_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.BLOCKED)}
    assert "production_guard_live_state_blocked" in ids


def test_blocked_have_blocker_reason():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.BLOCKED):
        assert c.next_action


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.OWNER_GATED):
        assert c.next_action


def test_no_autonomous_deploy_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.OWNER_GATED)}
    assert "production_guard_no_autonomous_deploy" in ids


EXPECTED_AREAS = {
    "commit_drift",
    "artifact_integrity",
    "certification_snapshot",
    "readiness_view",
    "rollback_safety",
    "production_guard",
}


def test_all_areas_covered():
    actual = {c.area for c in DEPLOYMENT_RECONCILIATION_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_commit_drift_area_has_criteria():
    assert len(get_criteria_by_area("commit_drift")) >= 3


def test_artifact_integrity_area_has_criteria():
    assert len(get_criteria_by_area("artifact_integrity")) >= 4


def test_certification_snapshot_area_has_criteria():
    assert len(get_criteria_by_area("certification_snapshot")) >= 3


def test_readiness_view_area_has_criteria():
    assert len(get_criteria_by_area("readiness_view")) >= 2


def test_rollback_safety_area_has_criteria():
    assert len(get_criteria_by_area("rollback_safety")) >= 3


def test_production_guard_area_has_criteria():
    assert len(get_criteria_by_area("production_guard")) >= 2


def test_commit_drift_detection_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "commit_drift_detection" in ids


def test_commit_drift_missing_sha_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "commit_drift_missing_sha" in ids


def test_commit_drift_no_production_action_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "commit_drift_no_production_action" in ids


def test_artifact_bundle_sha256_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "artifact_bundle_sha256" in ids


def test_artifact_bundle_commit_sha_minimum_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "artifact_bundle_commit_sha_minimum" in ids


def test_artifact_bundle_lanes_certified_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "artifact_bundle_lanes_certified" in ids


def test_artifact_bundle_no_production_action_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "artifact_bundle_no_production_action" in ids


def test_snapshot_hash_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "snapshot_snapshot_hash" in ids


def test_snapshot_certified_requires_both_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "snapshot_certified_requires_both" in ids


def test_snapshot_owner_authorization_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "snapshot_owner_authorization_required" in ids


def test_readiness_view_assembly_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "readiness_view_assembly" in ids


def test_readiness_view_no_production_action_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "readiness_view_no_production_action" in ids


def test_rollback_plan_required_fields_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "rollback_plan_required_fields" in ids


def test_rollback_tested_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "rollback_tested_required" in ids


def test_rollback_no_production_action_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeploymentReconciliationAuditStatus.READY)}
    assert "rollback_no_production_action" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == DeploymentReconciliationAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "deployment-reconciliation-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in DEPLOYMENT_RECONCILIATION_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {DeploymentReconciliationAuditStatus.READY, DeploymentReconciliationAuditStatus.GAP,
             DeploymentReconciliationAuditStatus.BLOCKED, DeploymentReconciliationAuditStatus.OWNER_GATED}
    for c in DEPLOYMENT_RECONCILIATION_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in DEPLOYMENT_RECONCILIATION_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in DEPLOYMENT_RECONCILIATION_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(DeploymentReconciliationAuditStatus.READY):
        assert c.status == DeploymentReconciliationAuditStatus.READY


def test_criterion_frozen():
    c = DEPLOYMENT_RECONCILIATION_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_drift_detection_evidence_cites_aligned():
    criterion = next(
        c for c in DEPLOYMENT_RECONCILIATION_CRITERIA
        if c.criterion_id == "commit_drift_detection"
    )
    assert "aligned" in criterion.evidence
    assert "deployed_commit_drift" in criterion.evidence


def test_artifact_bundle_evidence_cites_sha256():
    criterion = next(
        c for c in DEPLOYMENT_RECONCILIATION_CRITERIA
        if c.criterion_id == "artifact_bundle_sha256"
    )
    assert "sha256" in criterion.evidence.lower() or "SHA-256" in criterion.evidence
    assert "artifact_hash" in criterion.evidence


def test_no_autonomous_deploy_evidence_cites_all_false():
    criterion = next(
        c for c in DEPLOYMENT_RECONCILIATION_CRITERIA
        if c.criterion_id == "production_guard_no_autonomous_deploy"
    )
    assert "production_action_authorized: False" in criterion.evidence
    assert criterion.evidence.count("production_action_authorized: False") >= 3


def test_rollback_tested_evidence_cites_required_field():
    criterion = next(
        c for c in DEPLOYMENT_RECONCILIATION_CRITERIA
        if c.criterion_id == "rollback_tested_required"
    )
    assert "tested" in criterion.evidence
    assert "rollback_not_tested" in criterion.evidence


def test_snapshot_owner_authorization_evidence_cites_true():
    criterion = next(
        c for c in DEPLOYMENT_RECONCILIATION_CRITERIA
        if c.criterion_id == "snapshot_owner_authorization_required"
    )
    assert "owner_authorization_required: True" in criterion.evidence


def test_commit_drift_all_ready():
    commit_drift = get_criteria_by_area("commit_drift")
    assert commit_drift
    for c in commit_drift:
        assert c.status == DeploymentReconciliationAuditStatus.READY


def test_rollback_safety_all_ready():
    rollback = get_criteria_by_area("rollback_safety")
    assert rollback
    for c in rollback:
        assert c.status == DeploymentReconciliationAuditStatus.READY
