"""Tests for experience ledger audit (Approved Task Priority 21)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.experience_ledger_audit import (
    LEDGER_AUDIT_CRITERIA,
    LedgerAuditStatus,
    get_experience_ledger_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_experience_ledger_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "experience-ledger-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(LEDGER_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(LEDGER_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(LedgerAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(LedgerAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(LedgerAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(LedgerAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(LedgerAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(LedgerAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 2


def test_live_provider_outcome_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.BLOCKED)}
    assert "provider_live_outcome_capture" in ids


def test_durable_persistence_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.BLOCKED)}
    assert "durable_program_job_persistence" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(LedgerAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(LedgerAuditStatus.OWNER_GATED):
        assert c.next_action


def test_ledger_read_only_promotion_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.OWNER_GATED)}
    assert "security_ledger_read_only_promotion" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"outcome_capture", "replay", "failure", "provider", "planning", "security", "durable"}


def test_all_areas_covered():
    actual = {c.area for c in LEDGER_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from ledger audit"


def test_outcome_capture_area_has_criteria():
    assert len(get_criteria_by_area("outcome_capture")) >= 3


def test_replay_area_has_criteria():
    assert len(get_criteria_by_area("replay")) >= 2


def test_failure_area_has_criteria():
    assert len(get_criteria_by_area("failure")) >= 3


def test_provider_area_has_criteria():
    assert len(get_criteria_by_area("provider")) >= 2


def test_planning_area_has_criteria():
    assert len(get_criteria_by_area("planning")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_durable_area_has_criteria():
    assert len(get_criteria_by_area("durable")) >= 1


# Key criteria
def test_outcome_capture_program_job_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "outcome_capture_program_job" in ids


def test_outcome_capture_empirical_stats_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "outcome_capture_empirical_stats" in ids


def test_outcome_capture_receipt_coverage_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "outcome_capture_receipt_coverage" in ids


def test_replay_persisted_patch_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "replay_persisted_patch" in ids


def test_failure_blocked_outcome_record_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "failure_blocked_outcome_record" in ids


def test_failure_governance_boundary_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "failure_governance_boundary" in ids


def test_provider_no_api_park_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "provider_outcome_no_api_park" in ids


def test_planning_empirical_routing_feedback_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "planning_empirical_routing_feedback" in ids


def test_security_no_credential_in_ledger_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(LedgerAuditStatus.READY)}
    assert "security_no_credential_in_ledger" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == LedgerAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(LedgerAuditStatus.READY):
        assert c.status == LedgerAuditStatus.READY


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
    assert parsed["schema_version"] == "experience-ledger-audit/v1"


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
    ids = [c.criterion_id for c in LEDGER_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {LedgerAuditStatus.READY, LedgerAuditStatus.GAP,
             LedgerAuditStatus.BLOCKED, LedgerAuditStatus.OWNER_GATED}
    for c in LEDGER_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in LEDGER_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in LEDGER_AUDIT_CRITERIA:
        assert c.authoritative_module
