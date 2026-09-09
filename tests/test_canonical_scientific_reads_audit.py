"""Tests for canonical scientific reads audit (Approved Task Priority 13)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.canonical_scientific_reads_audit import (
    READS_AUDIT_CRITERIA,
    ReadsAuditStatus,
    get_canonical_scientific_reads_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_canonical_scientific_reads_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "canonical-scientific-reads-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(READS_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(READS_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(ReadsAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(ReadsAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(ReadsAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(ReadsAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 14


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(ReadsAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(ReadsAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_api_cited_in_blocked():
    blocked = _AUDIT.by_status(ReadsAuditStatus.BLOCKED)
    assert any("NO-API" in (c.blocker_reason or "") for c in blocked)


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(ReadsAuditStatus.OWNER_GATED):
        assert c.next_action


def test_no_autonomous_publish_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.OWNER_GATED)}
    assert "provenance_no_autonomous_publish" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"taxonomy", "occurrence", "elevation", "traits", "literature", "ecology", "provenance"}


def test_all_areas_covered():
    actual = {c.area for c in READS_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from reads audit"


def test_taxonomy_area_has_criteria():
    assert len(get_criteria_by_area("taxonomy")) >= 2


def test_occurrence_area_has_criteria():
    assert len(get_criteria_by_area("occurrence")) >= 2


def test_elevation_area_has_criteria():
    assert len(get_criteria_by_area("elevation")) >= 1


def test_traits_area_has_criteria():
    assert len(get_criteria_by_area("traits")) >= 2


def test_literature_area_has_criteria():
    assert len(get_criteria_by_area("literature")) >= 2


def test_ecology_area_has_criteria():
    assert len(get_criteria_by_area("ecology")) >= 2


def test_provenance_area_has_criteria():
    assert len(get_criteria_by_area("provenance")) >= 2


# Key criteria
def test_taxonomy_conservation_read_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "taxonomy_conservation_read" in ids


def test_occurrence_locality_withheld_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "occurrence_locality_withheld" in ids


def test_traits_vision_matrix_read_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "traits_vision_matrix_read" in ids


def test_traits_molecular_sequence_read_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "traits_molecular_sequence_read" in ids


def test_literature_evidence_synthesis_read_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "literature_evidence_synthesis_read" in ids


def test_ecology_globi_interaction_read_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "ecology_globi_interaction_read" in ids


def test_provenance_per_record_contract_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "provenance_per_record_contract" in ids


def test_provenance_repository_evidence_read_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadsAuditStatus.READY)}
    assert "provenance_repository_evidence_read" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == ReadsAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(ReadsAuditStatus.READY):
        assert c.status == ReadsAuditStatus.READY


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
    assert parsed["schema_version"] == "canonical-scientific-reads-audit/v1"


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
    ids = [c.criterion_id for c in READS_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {ReadsAuditStatus.READY, ReadsAuditStatus.GAP,
             ReadsAuditStatus.BLOCKED, ReadsAuditStatus.OWNER_GATED}
    for c in READS_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in READS_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in READS_AUDIT_CRITERIA:
        assert c.authoritative_module
