"""Tests for research station retrieval audit (Approved Task Priority 18)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.research_station_retrieval_audit import (
    RETRIEVAL_AUDIT_CRITERIA,
    RetrievalAuditStatus,
    get_research_station_retrieval_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_research_station_retrieval_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "research-station-retrieval-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(RETRIEVAL_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(RETRIEVAL_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(RetrievalAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(RetrievalAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(RetrievalAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(RetrievalAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(RetrievalAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(RetrievalAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 2


def test_semantic_index_unavailable_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.BLOCKED)}
    assert "query_semantic_index_availability" in ids


def test_live_europe_pmc_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.BLOCKED)}
    assert "failure_live_europe_pmc" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(RetrievalAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(RetrievalAuditStatus.OWNER_GATED):
        assert c.next_action


def test_no_autonomous_publication_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.OWNER_GATED)}
    assert "security_no_autonomous_publication" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"query", "planning", "attribution", "snippets", "failure", "literature", "security"}


def test_all_areas_covered():
    actual = {c.area for c in RETRIEVAL_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from retrieval audit"


def test_query_area_has_criteria():
    assert len(get_criteria_by_area("query")) >= 3


def test_planning_area_has_criteria():
    assert len(get_criteria_by_area("planning")) >= 2


def test_attribution_area_has_criteria():
    assert len(get_criteria_by_area("attribution")) >= 3


def test_snippets_area_has_criteria():
    assert len(get_criteria_by_area("snippets")) >= 2


def test_failure_area_has_criteria():
    assert len(get_criteria_by_area("failure")) >= 2


def test_literature_area_has_criteria():
    assert len(get_criteria_by_area("literature")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


# Key criteria
def test_query_retrieval_query_model_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "query_retrieval_query_model" in ids


def test_query_limit_bounds_validation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "query_limit_bounds_validation" in ids


def test_query_hybrid_mode_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "query_hybrid_mode" in ids


def test_planning_arbitrary_taxon_query_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "planning_arbitrary_taxon_query" in ids


def test_attribution_source_locator_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "attribution_source_locator" in ids


def test_attribution_ranking_explanation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "attribution_ranking_explanation" in ids


def test_snippets_external_citations_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "snippets_external_citations" in ids


def test_failure_safe_retrieval_fallback_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "failure_safe_retrieval_fallback" in ids


def test_failure_unavailable_evidence_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "failure_unavailable_evidence_state" in ids


def test_literature_review_required_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "literature_review_required_state" in ids


def test_security_internal_access_boundary_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RetrievalAuditStatus.READY)}
    assert "security_internal_access_boundary" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == RetrievalAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(RetrievalAuditStatus.READY):
        assert c.status == RetrievalAuditStatus.READY


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
    assert parsed["schema_version"] == "research-station-retrieval-audit/v1"


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
    ids = [c.criterion_id for c in RETRIEVAL_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {RetrievalAuditStatus.READY, RetrievalAuditStatus.GAP,
             RetrievalAuditStatus.BLOCKED, RetrievalAuditStatus.OWNER_GATED}
    for c in RETRIEVAL_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in RETRIEVAL_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in RETRIEVAL_AUDIT_CRITERIA:
        assert c.authoritative_module
