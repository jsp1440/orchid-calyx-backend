"""Tests for Relationship Matrix audit (Approved Task Priority 30)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.matrix_relationship_audit import (
    MATRIX_RELATIONSHIP_CRITERIA,
    MatrixRelationshipAuditStatus,
    get_matrix_relationship_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_matrix_relationship_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "matrix-relationship-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(MATRIX_RELATIONSHIP_CRITERIA) >= 14


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(MATRIX_RELATIONSHIP_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_db_required_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.BLOCKED)}
    assert "unavailable_db_required" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.BLOCKED):
        assert c.next_action


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.OWNER_GATED):
        assert c.next_action


def test_canonical_graph_mutation_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.OWNER_GATED)}
    assert "security_no_canonical_graph_mutation" in ids


EXPECTED_AREAS = {
    "evidence_coverage",
    "unavailable_dimensions",
    "neighborhood_quality",
    "relationship_path",
    "security",
}


def test_all_areas_covered():
    actual = {c.area for c in MATRIX_RELATIONSHIP_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_evidence_coverage_area_has_criteria():
    assert len(get_criteria_by_area("evidence_coverage")) >= 4


def test_unavailable_dimensions_area_has_criteria():
    assert len(get_criteria_by_area("unavailable_dimensions")) >= 3


def test_neighborhood_quality_area_has_criteria():
    assert len(get_criteria_by_area("neighborhood_quality")) >= 3


def test_relationship_path_area_has_criteria():
    assert len(get_criteria_by_area("relationship_path")) >= 4


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 3


def test_observational_default_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "evidence_class_observational_default" in ids


def test_evidence_class_hierarchy_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "evidence_class_hierarchy" in ids


def test_anchor_content_hash_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "evidence_anchors_content_hash" in ids


def test_absence_not_fabricated_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "evidence_absence_not_fabricated" in ids


def test_unavailable_distinct_from_absent_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "unavailable_distinct_from_absent" in ids


def test_candidate_probe_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "unavailable_candidate_probe" in ids


def test_compare_subjects_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "neighborhood_compare_subjects" in ids


def test_conflicting_preserved_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "neighborhood_conflicting_preserved" in ids


def test_state_counts_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "neighborhood_state_counts" in ids


def test_epistemic_state_vocab_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "path_epistemic_state_vocab" in ids


def test_path_disclaimer_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "path_disclaimer" in ids


def test_dimension_domain_mapping_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "path_dimension_domain_mapping" in ids


def test_confidence_bounded_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "path_confidence_bounded" in ids


def test_owner_auth_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "security_owner_auth_required" in ids


def test_safe_ident_validation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(MatrixRelationshipAuditStatus.READY)}
    assert "security_safe_ident_validation" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == MatrixRelationshipAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "matrix-relationship-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in MATRIX_RELATIONSHIP_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {MatrixRelationshipAuditStatus.READY, MatrixRelationshipAuditStatus.GAP,
             MatrixRelationshipAuditStatus.BLOCKED, MatrixRelationshipAuditStatus.OWNER_GATED}
    for c in MATRIX_RELATIONSHIP_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in MATRIX_RELATIONSHIP_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in MATRIX_RELATIONSHIP_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(MatrixRelationshipAuditStatus.READY):
        assert c.status == MatrixRelationshipAuditStatus.READY


def test_criterion_frozen():
    c = MATRIX_RELATIONSHIP_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_absence_not_fabricated_evidence_content():
    criterion = next(
        c for c in MATRIX_RELATIONSHIP_CRITERIA
        if c.criterion_id == "evidence_absence_not_fabricated"
    )
    assert "not_recorded" in criterion.evidence
    assert "biological absence" in criterion.evidence.lower()


def test_conflicting_evidence_preserved():
    criterion = next(
        c for c in MATRIX_RELATIONSHIP_CRITERIA
        if c.criterion_id == "neighborhood_conflicting_preserved"
    )
    assert "conflicting" in criterion.evidence
    assert "present" in criterion.evidence
    assert "absent" in criterion.evidence


def test_canonical_graph_mutation_false_in_evidence():
    criterion = next(
        c for c in MATRIX_RELATIONSHIP_CRITERIA
        if c.criterion_id == "security_no_canonical_graph_mutation"
    )
    assert "canonical_graph_mutation" in criterion.evidence
    assert "False" in criterion.evidence


def test_security_all_have_auth_module():
    for c in get_criteria_by_area("security"):
        assert c.authoritative_module
