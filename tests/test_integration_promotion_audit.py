"""Tests for integration-to-main gates audit (Approved Task Priority 34)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.integration_promotion_audit import (
    INTEGRATION_PROMOTION_CRITERIA,
    IntegrationPromotionAuditStatus,
    get_integration_promotion_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_integration_promotion_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "integration-promotion-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(INTEGRATION_PROMOTION_CRITERIA) >= 14


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(INTEGRATION_PROMOTION_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_audit_has_no_blocked():
    assert _AUDIT.blocked_count() == 0


def test_audit_has_owner_gated_items():
    assert _AUDIT.owner_gated_count() >= 1


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.OWNER_GATED):
        assert c.next_action


def test_deployment_coupling_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.OWNER_GATED)}
    assert "drift_deployment_coupling_owner_gated" in ids


EXPECTED_AREAS = {
    "main_protection",
    "production_risk",
    "validation_gates",
    "credential_scientific_protection",
    "drift_and_coupling",
}


def test_all_areas_covered():
    actual = {c.area for c in INTEGRATION_PROMOTION_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_main_protection_area_has_criteria():
    assert len(get_criteria_by_area("main_protection")) >= 3


def test_production_risk_area_has_criteria():
    assert len(get_criteria_by_area("production_risk")) >= 3


def test_validation_gates_area_has_criteria():
    assert len(get_criteria_by_area("validation_gates")) >= 4


def test_credential_scientific_protection_area_has_criteria():
    assert len(get_criteria_by_area("credential_scientific_protection")) >= 3


def test_drift_and_coupling_area_has_criteria():
    assert len(get_criteria_by_area("drift_and_coupling")) >= 3


def test_main_protection_owner_gate_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "main_protection_owner_gate" in ids


def test_main_protection_exception_policy_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "main_protection_exception_policy" in ids


def test_main_protection_integration_branch_only_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "main_protection_integration_branch_only" in ids


def test_production_risk_touches_production_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "production_risk_touches_production" in ids


def test_production_risk_destructive_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "production_risk_destructive" in ids


def test_production_risk_high_tier_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "production_risk_high_tier_owner_gated" in ids


def test_validation_independent_checker_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "validation_independent_checker" in ids


def test_validation_exact_head_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "validation_exact_head_required" in ids


def test_validation_required_checks_passed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "validation_required_checks_passed" in ids


def test_validation_checker_fail_repair_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "validation_checker_fail_routes_repair" in ids


def test_credentials_owner_gated_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "protection_credentials_owner_gated" in ids


def test_scientific_authority_owner_gated_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "protection_scientific_authority_owner_gated" in ids


def test_spending_owner_gated_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "protection_spending_owner_gated" in ids


def test_material_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "drift_material_fingerprint" in ids


def test_sensitive_locality_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(IntegrationPromotionAuditStatus.READY)}
    assert "drift_sensitive_locality_owner_gated" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == IntegrationPromotionAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "integration-promotion-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in INTEGRATION_PROMOTION_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {IntegrationPromotionAuditStatus.READY, IntegrationPromotionAuditStatus.GAP,
             IntegrationPromotionAuditStatus.BLOCKED, IntegrationPromotionAuditStatus.OWNER_GATED}
    for c in INTEGRATION_PROMOTION_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in INTEGRATION_PROMOTION_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in INTEGRATION_PROMOTION_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(IntegrationPromotionAuditStatus.READY):
        assert c.status == IntegrationPromotionAuditStatus.READY


def test_criterion_frozen():
    c = INTEGRATION_PROMOTION_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_main_protection_evidence_cites_owner_governed_boundary():
    criterion = next(
        c for c in INTEGRATION_PROMOTION_CRITERIA
        if c.criterion_id == "main_protection_owner_gate"
    )
    assert "OWNER_GOVERNED_BOUNDARY" in criterion.evidence
    assert "main" in criterion.evidence


def test_exception_policy_evidence_cites_protected_boundary():
    criterion = next(
        c for c in INTEGRATION_PROMOTION_CRITERIA
        if c.criterion_id == "main_protection_exception_policy"
    )
    assert "PROTECTED_BOUNDARIES" in criterion.evidence
    assert "integration_main_promotion" in criterion.evidence


def test_independent_checker_evidence_cites_maker_identity():
    criterion = next(
        c for c in INTEGRATION_PROMOTION_CRITERIA
        if c.criterion_id == "validation_independent_checker"
    )
    assert "maker_id" in criterion.evidence
    assert "checker_id" in criterion.evidence


def test_fingerprint_evidence_cites_sha256():
    criterion = next(
        c for c in INTEGRATION_PROMOTION_CRITERIA
        if c.criterion_id == "drift_material_fingerprint"
    )
    assert "SHA-256" in criterion.evidence or "sha256" in criterion.evidence.lower()
    assert "head_sha" in criterion.evidence


def test_main_protection_all_ready():
    main_protection = get_criteria_by_area("main_protection")
    assert main_protection
    for c in main_protection:
        assert c.status == IntegrationPromotionAuditStatus.READY


def test_validation_gates_all_ready():
    validation = get_criteria_by_area("validation_gates")
    assert validation
    for c in validation:
        assert c.status == IntegrationPromotionAuditStatus.READY
