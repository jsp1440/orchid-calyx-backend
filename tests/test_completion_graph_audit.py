"""Tests for recursive completion graph audit (Approved Task Priority 24)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.completion_graph_audit import (
    COMPLETION_GRAPH_CRITERIA,
    CompletionGraphAuditStatus,
    get_completion_graph_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_completion_graph_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "completion-graph-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(COMPLETION_GRAPH_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(COMPLETION_GRAPH_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 14


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_live_graph_state_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.BLOCKED)}
    assert "dependencies_live_graph_state" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(CompletionGraphAuditStatus.OWNER_GATED):
        assert c.next_action


def test_owner_gate_merge_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.OWNER_GATED)}
    assert "blockers_owner_gate_merge" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"leaves", "acceptance", "dependencies", "priorities", "blockers", "stale_superseded", "security"}


def test_all_areas_covered():
    actual = {c.area for c in COMPLETION_GRAPH_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from completion graph audit"


def test_leaves_area_has_criteria():
    assert len(get_criteria_by_area("leaves")) >= 3


def test_acceptance_area_has_criteria():
    assert len(get_criteria_by_area("acceptance")) >= 2


def test_dependencies_area_has_criteria():
    assert len(get_criteria_by_area("dependencies")) >= 2


def test_priorities_area_has_criteria():
    assert len(get_criteria_by_area("priorities")) >= 2


def test_blockers_area_has_criteria():
    assert len(get_criteria_by_area("blockers")) >= 2


def test_stale_superseded_area_has_criteria():
    assert len(get_criteria_by_area("stale_superseded")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


# Key criteria — leaves
def test_approved_task_reservoir_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "leaves_approved_task_reservoir" in ids


def test_bounded_lane_width_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "leaves_bounded_lane_width" in ids


def test_completion_state_enum_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "leaves_completion_state_enum" in ids


def test_specialist_cap_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "leaves_specialist_cap" in ids


# Key criteria — acceptance
def test_immutable_artifact_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "acceptance_immutable_artifact" in ids


def test_completion_receipt_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "acceptance_completion_receipt" in ids


def test_halted_unsafe_pr_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "acceptance_halted_unsafe_pr_state" in ids


# Key criteria — dependencies
def test_priority_ordered_queue_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "dependencies_priority_ordered_queue" in ids


def test_approved_task_sequence_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "dependencies_approved_task_sequence" in ids


# Key criteria — blockers
def test_halted_repair_limit_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "blockers_halted_repair_limit" in ids


def test_database_url_missing_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "blockers_database_url_missing" in ids


# Key criteria — stale_superseded
def test_mission_states_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "stale_superseded_mission_states" in ids


def test_stale_record_review_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "stale_superseded_stale_record_review" in ids


def test_completion_loop_stale_checks_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "stale_superseded_completion_loop_stale_checks" in ids


# Key criteria — security
def test_no_main_merge_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "security_no_main_merge" in ids


def test_lease_atomicity_claim_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CompletionGraphAuditStatus.READY)}
    assert "security_lease_atomicity_claim" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == CompletionGraphAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(CompletionGraphAuditStatus.READY):
        assert c.status == CompletionGraphAuditStatus.READY


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
    assert parsed["schema_version"] == "completion-graph-audit/v1"


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
    ids = [c.criterion_id for c in COMPLETION_GRAPH_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {CompletionGraphAuditStatus.READY, CompletionGraphAuditStatus.GAP,
             CompletionGraphAuditStatus.BLOCKED, CompletionGraphAuditStatus.OWNER_GATED}
    for c in COMPLETION_GRAPH_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in COMPLETION_GRAPH_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in COMPLETION_GRAPH_CRITERIA:
        assert c.authoritative_module
