"""Tests for no-idle lane refill audit (Approved Task Priority 26)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.lane_refill_audit import (
    LANE_REFILL_CRITERIA,
    LaneRefillAuditStatus,
    get_lane_refill_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_lane_refill_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "lane-refill-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(LANE_REFILL_CRITERIA) >= 8


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(LANE_REFILL_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 7


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_api_provider_wait_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.BLOCKED)}
    assert "provider_wait_no_api_mode" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.BLOCKED):
        assert c.next_action


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(LaneRefillAuditStatus.OWNER_GATED):
        assert c.next_action


def test_no_owner_gate_bypass_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.OWNER_GATED)}
    assert "security_no_owner_gate_bypass" in ids


EXPECTED_AREAS = {"completion_refill", "block_refill", "provider_wait_refill", "ci_wait_refill", "security"}


def test_all_areas_covered():
    actual = {c.area for c in LANE_REFILL_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_completion_refill_area_has_criteria():
    assert len(get_criteria_by_area("completion_refill")) >= 2


def test_block_refill_area_has_criteria():
    assert len(get_criteria_by_area("block_refill")) >= 2


def test_provider_wait_refill_area_has_criteria():
    assert len(get_criteria_by_area("provider_wait_refill")) >= 1


def test_ci_wait_refill_area_has_criteria():
    assert len(get_criteria_by_area("ci_wait_refill")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_run_once_refill_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "completion_run_once_refill" in ids


def test_idle_reason_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "completion_idle_reason" in ids


def test_blocked_approval_parking_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "block_refill_blocked_approval" in ids


def test_park_provider_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "provider_wait_park_provider_required" in ids


def test_waiting_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "ci_wait_waiting_state" in ids


def test_repair_committed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "ci_wait_repair_committed" in ids


def test_lease_claim_atomicity_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "security_lease_claim_atomicity" in ids


def test_expired_lease_reclaim_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LaneRefillAuditStatus.READY)}
    assert "security_expired_lease_reclaim" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == LaneRefillAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "lane-refill-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in LANE_REFILL_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {LaneRefillAuditStatus.READY, LaneRefillAuditStatus.GAP,
             LaneRefillAuditStatus.BLOCKED, LaneRefillAuditStatus.OWNER_GATED}
    for c in LANE_REFILL_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in LANE_REFILL_CRITERIA:
        assert c.evidence


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(LaneRefillAuditStatus.READY):
        assert c.status == LaneRefillAuditStatus.READY
