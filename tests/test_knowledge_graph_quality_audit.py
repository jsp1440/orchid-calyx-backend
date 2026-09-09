"""Tests for Knowledge Graph quality audit (Approved Task Priority 20)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.knowledge_graph_quality_audit import (
    KG_QUALITY_CRITERIA,
    KGQualityAuditStatus,
    get_knowledge_graph_quality_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_knowledge_graph_quality_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "knowledge-graph-quality-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(KG_QUALITY_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(KG_QUALITY_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(KGQualityAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(KGQualityAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(KGQualityAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(KGQualityAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(KGQualityAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(KGQualityAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_live_contradiction_resolution_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.BLOCKED)}
    assert "contradictions_live_resolution" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(KGQualityAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(KGQualityAuditStatus.OWNER_GATED):
        assert c.next_action


def test_live_kg_edge_write_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.OWNER_GATED)}
    assert "edges_live_kg_write" in ids


def test_mutation_owner_authorization_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.OWNER_GATED)}
    assert "mutation_owner_authorization_required" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"coverage", "contradictions", "orphans", "edges", "staleness", "provenance", "mutation"}


def test_all_areas_covered():
    actual = {c.area for c in KG_QUALITY_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from KG quality audit"


def test_coverage_area_has_criteria():
    assert len(get_criteria_by_area("coverage")) >= 3


def test_contradictions_area_has_criteria():
    assert len(get_criteria_by_area("contradictions")) >= 2


def test_orphans_area_has_criteria():
    assert len(get_criteria_by_area("orphans")) >= 2


def test_edges_area_has_criteria():
    assert len(get_criteria_by_area("edges")) >= 2


def test_staleness_area_has_criteria():
    assert len(get_criteria_by_area("staleness")) >= 2


def test_provenance_area_has_criteria():
    assert len(get_criteria_by_area("provenance")) >= 2


def test_mutation_area_has_criteria():
    assert len(get_criteria_by_area("mutation")) >= 2


# Key criteria
def test_coverage_source_registry_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "coverage_source_registry" in ids


def test_coverage_source_kind_taxonomy_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "coverage_source_kind_taxonomy" in ids


def test_contradictions_source_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "contradictions_source_state" in ids


def test_orphans_artifact_evidence_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "orphans_artifact_evidence_required" in ids


def test_edges_graph_operation_provenance_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "edges_graph_operation_provenance" in ids


def test_staleness_source_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "staleness_source_state" in ids


def test_provenance_source_registration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "provenance_source_registration" in ids


def test_mutation_candidate_knowledge_review_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(KGQualityAuditStatus.READY)}
    assert "mutation_candidate_knowledge_review" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == KGQualityAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(KGQualityAuditStatus.READY):
        assert c.status == KGQualityAuditStatus.READY


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
    assert parsed["schema_version"] == "knowledge-graph-quality-audit/v1"


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
    ids = [c.criterion_id for c in KG_QUALITY_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {KGQualityAuditStatus.READY, KGQualityAuditStatus.GAP,
             KGQualityAuditStatus.BLOCKED, KGQualityAuditStatus.OWNER_GATED}
    for c in KG_QUALITY_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in KG_QUALITY_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in KG_QUALITY_CRITERIA:
        assert c.authoritative_module
