"""Tests for Calyx acceptance mission audit (Approved Task Priority 14)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.calyx_acceptance_mission_audit import (
    ACCEPTANCE_MISSION_CRITERIA,
    AcceptanceMissionStatus,
    get_calyx_acceptance_mission_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_calyx_acceptance_mission_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "calyx-acceptance-mission-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(ACCEPTANCE_MISSION_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(ACCEPTANCE_MISSION_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 15


# GAP
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.GAP):
        assert c.gap_description


# BLOCKED
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_api_cited_in_blocked():
    blocked = _AUDIT.by_status(AcceptanceMissionStatus.BLOCKED)
    assert any("NO-API" in (c.blocker_reason or "") for c in blocked)


# OWNER_GATED
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(AcceptanceMissionStatus.OWNER_GATED):
        assert c.next_action


def test_publication_gated_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.OWNER_GATED)}
    assert "security_acceptance_publication_gated" in ids


# Area coverage
EXPECTED_AREAS = {"canonical_evidence", "synthesis", "citations", "uncertainty", "artifact", "replay", "security"}


def test_all_areas_covered():
    actual = {c.area for c in ACCEPTANCE_MISSION_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing"


def test_canonical_evidence_area_has_criteria():
    assert len(get_criteria_by_area("canonical_evidence")) >= 2


def test_synthesis_area_has_criteria():
    assert len(get_criteria_by_area("synthesis")) >= 2


def test_citations_area_has_criteria():
    assert len(get_criteria_by_area("citations")) >= 2


def test_uncertainty_area_has_criteria():
    assert len(get_criteria_by_area("uncertainty")) >= 2


def test_artifact_area_has_criteria():
    assert len(get_criteria_by_area("artifact")) >= 1


def test_replay_area_has_criteria():
    assert len(get_criteria_by_area("replay")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


# Key criteria
def test_canonical_evidence_read_only_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "canonical_evidence_read_only_enforcement" in ids


def test_synthesis_teaching_v1_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "synthesis_teaching_v1_mission" in ids


def test_citations_no_fabrication_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "citations_no_fabrication" in ids


def test_uncertainty_evidence_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "uncertainty_evidence_state_disclosure" in ids


def test_artifact_immutable_registration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "artifact_immutable_registration" in ids


def test_replay_idempotent_executor_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "replay_idempotent_executor" in ids


def test_replay_event_continuation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "replay_event_continuation" in ids


def test_security_mission_read_only_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(AcceptanceMissionStatus.READY)}
    assert "security_mission_read_only_enforced" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == AcceptanceMissionStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(AcceptanceMissionStatus.READY):
        assert c.status == AcceptanceMissionStatus.READY


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
    assert parsed["schema_version"] == "calyx-acceptance-mission-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']:
        assert key not in output


# Structure
def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in ACCEPTANCE_MISSION_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {AcceptanceMissionStatus.READY, AcceptanceMissionStatus.GAP,
             AcceptanceMissionStatus.BLOCKED, AcceptanceMissionStatus.OWNER_GATED}
    for c in ACCEPTANCE_MISSION_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in ACCEPTANCE_MISSION_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in ACCEPTANCE_MISSION_CRITERIA:
        assert c.authoritative_module
