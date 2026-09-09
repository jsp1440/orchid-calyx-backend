"""Tests for lease atomicity audit (Approved Task Priority 28)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.lease_atomicity_audit import (
    LEASE_ATOMICITY_CRITERIA,
    LeaseAtomicityStatus,
    get_lease_atomicity_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_lease_atomicity_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "lease-atomicity-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(LEASE_ATOMICITY_CRITERIA) >= 10


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(LEASE_ATOMICITY_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 8


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_durable_lease_db_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.BLOCKED)}
    assert "security_durable_lease_requires_db" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.BLOCKED):
        assert c.next_action


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(LeaseAtomicityStatus.OWNER_GATED):
        assert c.next_action


def test_no_owner_gate_lease_bypass_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.OWNER_GATED)}
    assert "security_no_owner_gate_lease_bypass" in ids


EXPECTED_AREAS = {"atomic_claim", "transition", "stale_reclaim", "security"}


def test_all_areas_covered():
    actual = {c.area for c in LEASE_ATOMICITY_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_atomic_claim_area_has_criteria():
    assert len(get_criteria_by_area("atomic_claim")) >= 2


def test_transition_area_has_criteria():
    assert len(get_criteria_by_area("transition")) >= 2


def test_stale_reclaim_area_has_criteria():
    assert len(get_criteria_by_area("stale_reclaim")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_for_update_skip_locked_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "atomic_claim_for_update_skip_locked" in ids


def test_scheduler_lease_token_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "atomic_claim_scheduler_lease_token" in ids


def test_lease_duration_bounds_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "atomic_claim_lease_duration_bounds" in ids


def test_queued_to_running_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "transition_queued_to_running" in ids


def test_approved_to_queued_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "transition_approved_to_queued" in ids


def test_validate_mission_transition_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "transition_validate_mission_transition" in ids


def test_recover_expired_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "stale_reclaim_recover_expired" in ids


def test_scheduler_expired_leases_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "stale_reclaim_scheduler_expired_leases" in ids


def test_renew_lease_fencing_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "stale_reclaim_renew_lease_fencing" in ids


def test_lease_token_validation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LeaseAtomicityStatus.READY)}
    assert "security_lease_token_validation" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == LeaseAtomicityStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "lease-atomicity-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in LEASE_ATOMICITY_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {LeaseAtomicityStatus.READY, LeaseAtomicityStatus.GAP,
             LeaseAtomicityStatus.BLOCKED, LeaseAtomicityStatus.OWNER_GATED}
    for c in LEASE_ATOMICITY_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in LEASE_ATOMICITY_CRITERIA:
        assert c.evidence


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(LeaseAtomicityStatus.READY):
        assert c.status == LeaseAtomicityStatus.READY
