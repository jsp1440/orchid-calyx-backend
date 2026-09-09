"""Tests for frontend/backend contracts audit (Approved Task Priority 36)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.frontend_contracts_audit import (
    FRONTEND_CONTRACTS_CRITERIA,
    FrontendContractsAuditStatus,
    get_frontend_contracts_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_frontend_contracts_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "frontend-contracts-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(FRONTEND_CONTRACTS_CRITERIA) >= 14


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(FRONTEND_CONTRACTS_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_stale_endpoint_risk_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.BLOCKED)}
    assert "frontend_contract_stale_endpoint_risk" in ids


def test_blocked_have_blocker_reason():
    for c in _AUDIT.by_status(FrontendContractsAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(FrontendContractsAuditStatus.BLOCKED):
        assert c.next_action


EXPECTED_AREAS = {
    "route_schema",
    "degraded_states",
    "auth_boundaries",
    "scientific_contract",
    "frontend_evidence_contract",
}


def test_all_areas_covered():
    actual = {c.area for c in FRONTEND_CONTRACTS_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_route_schema_area_has_criteria():
    assert len(get_criteria_by_area("route_schema")) >= 3


def test_degraded_states_area_has_criteria():
    assert len(get_criteria_by_area("degraded_states")) >= 3


def test_auth_boundaries_area_has_criteria():
    assert len(get_criteria_by_area("auth_boundaries")) >= 4


def test_scientific_contract_area_has_criteria():
    assert len(get_criteria_by_area("scientific_contract")) >= 4


def test_frontend_evidence_contract_area_has_criteria():
    assert len(get_criteria_by_area("frontend_evidence_contract")) >= 2


def test_route_schema_prefix_stable_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "route_schema_prefix_stable" in ids


def test_route_schema_runner_prefix_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "route_schema_runner_prefix" in ids


def test_route_schema_version_field_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "route_schema_version_field" in ids


def test_degraded_fail_closed_no_db_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "degraded_fail_closed_no_db" in ids


def test_degraded_brain_integration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "degraded_brain_integration" in ids


def test_degraded_kernel_health_surface_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "degraded_kernel_health_surface" in ids


def test_auth_write_endpoints_api_key_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "auth_write_endpoints_api_key" in ids


def test_auth_constant_time_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "auth_api_key_constant_time_compare" in ids


def test_auth_owner_session_signed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "auth_owner_session_signed" in ids


def test_auth_read_list_unauthenticated_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "auth_read_list_unauthenticated" in ids


def test_cannot_determine_preserved_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "scientific_cannot_determine_preserved" in ids


def test_machine_generated_entry_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "scientific_machine_generated_entry_state" in ids


def test_absolute_unit_calibration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "scientific_absolute_unit_calibration" in ids


def test_color_evidence_bounded_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "scientific_color_evidence_bounded" in ids


def test_frontend_evidence_summary_flat_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FrontendContractsAuditStatus.READY)}
    assert "frontend_evidence_summary_flat" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == FrontendContractsAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "frontend-contracts-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in FRONTEND_CONTRACTS_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {FrontendContractsAuditStatus.READY, FrontendContractsAuditStatus.GAP,
             FrontendContractsAuditStatus.BLOCKED, FrontendContractsAuditStatus.OWNER_GATED}
    for c in FRONTEND_CONTRACTS_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in FRONTEND_CONTRACTS_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in FRONTEND_CONTRACTS_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(FrontendContractsAuditStatus.READY):
        assert c.status == FrontendContractsAuditStatus.READY


def test_criterion_frozen():
    c = FRONTEND_CONTRACTS_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_auth_constant_time_evidence_cites_hmac():
    criterion = next(
        c for c in FRONTEND_CONTRACTS_CRITERIA
        if c.criterion_id == "auth_api_key_constant_time_compare"
    )
    assert "hmac.compare_digest" in criterion.evidence


def test_cannot_determine_evidence_cites_no_collapse():
    criterion = next(
        c for c in FRONTEND_CONTRACTS_CRITERIA
        if c.criterion_id == "scientific_cannot_determine_preserved"
    )
    assert "CANNOT_DETERMINE" in criterion.evidence
    assert "never" in criterion.evidence.lower() or "must not" in criterion.evidence.lower()


def test_machine_generated_evidence_cites_no_auto_promotion():
    criterion = next(
        c for c in FRONTEND_CONTRACTS_CRITERIA
        if c.criterion_id == "scientific_machine_generated_entry_state"
    )
    assert "MACHINE_GENERATED" in criterion.evidence
    assert "auto" in criterion.evidence.lower() or "promotion" in criterion.evidence.lower()


def test_absolute_unit_evidence_cites_calibration_error():
    criterion = next(
        c for c in FRONTEND_CONTRACTS_CRITERIA
        if c.criterion_id == "scientific_absolute_unit_calibration"
    )
    assert "ABSOLUTE_UNIT_REQUIRES_CALIBRATION" in criterion.evidence
    assert "CALIBRATED_SCALE" in criterion.evidence


def test_route_schema_prefix_evidence_cites_api_prefix():
    criterion = next(
        c for c in FRONTEND_CONTRACTS_CRITERIA
        if c.criterion_id == "route_schema_prefix_stable"
    )
    assert "/api/vision-lexicon" in criterion.evidence


def test_auth_write_evidence_cites_write_auth():
    criterion = next(
        c for c in FRONTEND_CONTRACTS_CRITERIA
        if c.criterion_id == "auth_write_endpoints_api_key"
    )
    assert "WRITE_AUTH" in criterion.evidence
    assert "verify_api_key" in criterion.evidence


def test_route_schema_all_ready():
    route_schema = get_criteria_by_area("route_schema")
    assert route_schema
    for c in route_schema:
        assert c.status == FrontendContractsAuditStatus.READY


def test_auth_boundaries_all_ready():
    auth = get_criteria_by_area("auth_boundaries")
    assert auth
    for c in auth:
        assert c.status == FrontendContractsAuditStatus.READY
