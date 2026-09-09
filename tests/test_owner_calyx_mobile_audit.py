"""Tests for owner Calyx mobile experience audit (Approved Task Priority 15)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.owner_calyx_mobile_audit import (
    MOBILE_AUDIT_CRITERIA,
    MobileAuditStatus,
    get_owner_calyx_mobile_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_owner_calyx_mobile_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "owner-calyx-mobile-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(MOBILE_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(MOBILE_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(MobileAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(MobileAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(MobileAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(MobileAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 14


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(MobileAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(MobileAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_api_cited_in_blocked():
    blocked = _AUDIT.by_status(MobileAuditStatus.BLOCKED)
    assert any("NO-API" in (c.blocker_reason or "") for c in blocked)


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(MobileAuditStatus.OWNER_GATED):
        assert c.next_action


# Area coverage — all 7 areas
EXPECTED_AREAS = {"shell", "sessions", "streaming", "citations", "uncertainty", "live_status", "degraded"}


def test_all_areas_covered():
    actual = {c.area for c in MOBILE_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from mobile audit"


def test_shell_area_has_criteria():
    assert len(get_criteria_by_area("shell")) >= 2


def test_sessions_area_has_criteria():
    assert len(get_criteria_by_area("sessions")) >= 2


def test_streaming_area_has_criteria():
    assert len(get_criteria_by_area("streaming")) >= 2


def test_citations_area_has_criteria():
    assert len(get_criteria_by_area("citations")) >= 2


def test_uncertainty_area_has_criteria():
    assert len(get_criteria_by_area("uncertainty")) >= 2


def test_live_status_area_has_criteria():
    assert len(get_criteria_by_area("live_status")) >= 2


def test_degraded_area_has_criteria():
    assert len(get_criteria_by_area("degraded")) >= 2


# Key criteria
def test_shell_speak_router_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "shell_speak_router" in ids


def test_shell_auth_guard_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "shell_authentication_guard" in ids


def test_sessions_persistent_store_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "sessions_persistent_store" in ids


def test_sessions_postgres_durable_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.BLOCKED)}
    assert "sessions_postgres_durable" in ids


def test_streaming_governed_turn_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "streaming_governed_turn" in ids


def test_streaming_live_sse_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.BLOCKED)}
    assert "streaming_live_sse" in ids


def test_citations_external_trail_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "citations_external_trail" in ids


def test_citations_reference_trail_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "citations_reference_trail" in ids


def test_uncertainty_casual_mode_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "uncertainty_casual_mode" in ids


def test_live_status_endpoint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "live_status_endpoint" in ids


def test_live_status_provider_disclosure_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "live_status_provider_disclosure" in ids


def test_degraded_deterministic_governed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "degraded_deterministic_governed" in ids


def test_degraded_safe_retrieval_fallback_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MobileAuditStatus.READY)}
    assert "degraded_safe_retrieval_fallback" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == MobileAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(MobileAuditStatus.READY):
        assert c.status == MobileAuditStatus.READY


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["area"]
        assert action["title"]
        assert action["status"]
        assert action["next_action"]


# Serialization
def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "owner-calyx-mobile-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']:
        assert key not in output


# Structure
def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in MOBILE_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {MobileAuditStatus.READY, MobileAuditStatus.GAP,
             MobileAuditStatus.BLOCKED, MobileAuditStatus.OWNER_GATED}
    for c in MOBILE_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in MOBILE_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in MOBILE_AUDIT_CRITERIA:
        assert c.authoritative_module
