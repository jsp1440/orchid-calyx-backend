"""Tests for research station persistence audit (Approved Task Priority 17)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.research_station_persistence_audit import (
    PERSISTENCE_AUDIT_CRITERIA,
    PersistenceAuditStatus,
    get_research_station_persistence_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_research_station_persistence_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "research-station-persistence-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(PERSISTENCE_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(PERSISTENCE_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(PersistenceAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(PersistenceAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(PersistenceAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(PersistenceAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 14


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(PersistenceAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(PersistenceAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_database_url_blocker_present():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.BLOCKED)}
    assert "storage_database_url_durable" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(PersistenceAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(PersistenceAuditStatus.OWNER_GATED):
        assert c.next_action


def test_publication_authority_separation_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.OWNER_GATED)}
    assert "security_publication_authority_separation" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"request", "result", "provenance", "artifact", "idempotency", "storage", "security"}


def test_all_areas_covered():
    actual = {c.area for c in PERSISTENCE_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from persistence audit"


def test_request_area_has_criteria():
    assert len(get_criteria_by_area("request")) >= 2


def test_result_area_has_criteria():
    assert len(get_criteria_by_area("result")) >= 2


def test_provenance_area_has_criteria():
    assert len(get_criteria_by_area("provenance")) >= 2


def test_artifact_area_has_criteria():
    assert len(get_criteria_by_area("artifact")) >= 2


def test_idempotency_area_has_criteria():
    assert len(get_criteria_by_area("idempotency")) >= 2


def test_storage_area_has_criteria():
    assert len(get_criteria_by_area("storage")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


# Key criteria
def test_request_program_job_persistence_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "request_program_job_persistence" in ids


def test_result_terminal_outcome_record_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "result_terminal_outcome_record" in ids


def test_result_github_feedback_idempotent_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "result_github_feedback_idempotent" in ids


def test_provenance_artifact_registration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "provenance_artifact_registration" in ids


def test_provenance_evidence_link_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "provenance_evidence_link_required" in ids


def test_artifact_immutable_sha256_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "artifact_immutable_sha256" in ids


def test_artifact_idempotent_registration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "artifact_idempotent_registration" in ids


def test_idempotency_persisted_patch_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "idempotency_persisted_patch_verification" in ids


def test_idempotency_create_or_touch_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "idempotency_create_or_touch" in ids


def test_storage_dual_mode_default_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "storage_dual_mode_default" in ids


def test_security_no_credential_in_artifact_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(PersistenceAuditStatus.READY)}
    assert "security_no_credential_in_artifact" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == PersistenceAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(PersistenceAuditStatus.READY):
        assert c.status == PersistenceAuditStatus.READY


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
    assert parsed["schema_version"] == "research-station-persistence-audit/v1"


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
    ids = [c.criterion_id for c in PERSISTENCE_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {PersistenceAuditStatus.READY, PersistenceAuditStatus.GAP,
             PersistenceAuditStatus.BLOCKED, PersistenceAuditStatus.OWNER_GATED}
    for c in PERSISTENCE_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in PERSISTENCE_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in PERSISTENCE_AUDIT_CRITERIA:
        assert c.authoritative_module
