"""Tests for epistemic memory audit (Approved Task Priority 22)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.epistemic_memory_audit import (
    EPISTEMIC_AUDIT_CRITERIA,
    EpistemicAuditStatus,
    get_epistemic_memory_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_epistemic_memory_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "epistemic-memory-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(EPISTEMIC_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(EPISTEMIC_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(EpistemicAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(EpistemicAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(EpistemicAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(EpistemicAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(EpistemicAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(EpistemicAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_live_durable_memory_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.BLOCKED)}
    assert "memory_live_durable_sessions" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(EpistemicAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(EpistemicAuditStatus.OWNER_GATED):
        assert c.next_action


# Area coverage — all 7 areas
EXPECTED_AREAS = {"distinctions", "contradictions", "confidence", "uncertainty", "provenance", "security", "memory"}


def test_all_areas_covered():
    actual = {c.area for c in EPISTEMIC_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from epistemic memory audit"


def test_distinctions_area_has_criteria():
    assert len(get_criteria_by_area("distinctions")) >= 3


def test_contradictions_area_has_criteria():
    assert len(get_criteria_by_area("contradictions")) >= 2


def test_confidence_area_has_criteria():
    assert len(get_criteria_by_area("confidence")) >= 2


def test_uncertainty_area_has_criteria():
    assert len(get_criteria_by_area("uncertainty")) >= 2


def test_provenance_area_has_criteria():
    assert len(get_criteria_by_area("provenance")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_memory_area_has_criteria():
    assert len(get_criteria_by_area("memory")) >= 1


# Key criteria — distinctions
def test_evidence_state_enum_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "distinctions_evidence_state_enum" in ids


def test_source_trust_class_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "distinctions_source_trust_class" in ids


def test_evidence_provenance_survival_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "distinctions_evidence_provenance_survival" in ids


def test_domain_evidence_claim_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "distinctions_domain_evidence_claim" in ids


# Key criteria — contradictions
def test_contradictions_not_resolved_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "contradictions_not_resolved" in ids


def test_contradictions_evidence_state_conflict_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "contradictions_evidence_state_conflict" in ids


def test_contradictions_kg_source_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "contradictions_kg_source_state" in ids


# Key criteria — confidence
def test_vision_matrix_cap_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "confidence_vision_matrix_cap" in ids


def test_success_rate_semantics_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "confidence_success_rate_semantics" in ids


# Key criteria — uncertainty
def test_knowledge_gaps_list_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "uncertainty_knowledge_gaps_list" in ids


def test_unavailable_evidence_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "uncertainty_unavailable_evidence_state" in ids


def test_gap_evidence_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "uncertainty_gap_evidence_state" in ids


# Key criteria — provenance
def test_per_claim_provenance_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "provenance_per_claim" in ids


def test_locality_withheld_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "provenance_locality_withheld" in ids


def test_brain_candidate_checksum_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "provenance_brain_candidate_checksum" in ids


# Key criteria — security
def test_no_fabricated_claims_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "security_no_fabricated_claims" in ids


def test_graph_mutation_false_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "security_graph_mutation_false" in ids


# Key criteria — memory
def test_conversation_context_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(EpistemicAuditStatus.READY)}
    assert "memory_conversation_context" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == EpistemicAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(EpistemicAuditStatus.READY):
        assert c.status == EpistemicAuditStatus.READY


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
    assert parsed["schema_version"] == "epistemic-memory-audit/v1"


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
    ids = [c.criterion_id for c in EPISTEMIC_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {EpistemicAuditStatus.READY, EpistemicAuditStatus.GAP,
             EpistemicAuditStatus.BLOCKED, EpistemicAuditStatus.OWNER_GATED}
    for c in EPISTEMIC_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in EPISTEMIC_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in EPISTEMIC_AUDIT_CRITERIA:
        assert c.authoritative_module
