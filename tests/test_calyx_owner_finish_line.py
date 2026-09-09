"""Tests for Calyx owner finish-line audit (Approved Task Priority 1).

Proves:
- All finish-line criteria are present and serializable
- READY criteria have non-empty evidence and no gap_description
- GAP criteria have gap_description and next_action
- BLOCKED criteria have blocker_reason
- OWNER_GATED criteria require explicit authorization (next_action non-empty)
- no_auto_publication and no_production_mutation are always True
- Audit summary counts are consistent
- JSON output contains no secrets or coordinate fields
- get_gaps() returns only GAP-status criteria
- get_next_actions() returns only criteria with next_action defined
"""

from __future__ import annotations

import json

from app.scientific_adapter_lab.calyx_owner_finish_line import (
    FINISH_LINE_CRITERIA,
    FinishLineStatus,
    get_criteria_by_status,
    get_finish_line_audit,
    get_gaps,
    get_next_actions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUDIT = get_finish_line_audit()
_DICT = _AUDIT.to_dict()


# ---------------------------------------------------------------------------
# Schema / structure
# ---------------------------------------------------------------------------

def test_schema_version_present():
    assert _DICT["schema_version"] == "calyx-owner-finish-line/v1"


def test_audit_date_present():
    assert _DICT["audit_date"]
    assert len(_DICT["audit_date"]) == 10  # YYYY-MM-DD


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(FINISH_LINE_CRITERIA) >= 10


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(FINISH_LINE_CRITERIA)


# ---------------------------------------------------------------------------
# READY criteria
# ---------------------------------------------------------------------------

def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(FinishLineStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but has no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(FinishLineStatus.READY):
        assert c.gap_description is None, (
            f"{c.criterion_id} is READY but has gap_description"
        )


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(FinishLineStatus.READY):
        assert c.blocker_reason is None, (
            f"{c.criterion_id} is READY but has blocker_reason"
        )


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(FinishLineStatus.READY):
        assert c.next_action is None, (
            f"{c.criterion_id} is READY but has next_action"
        )


# ---------------------------------------------------------------------------
# GAP criteria
# ---------------------------------------------------------------------------

def test_gap_criteria_have_gap_description():
    gaps = _AUDIT.by_status(FinishLineStatus.GAP)
    assert gaps, "Expected at least one GAP criterion"
    for c in gaps:
        assert c.gap_description, f"{c.criterion_id} GAP but missing gap_description"


def test_gap_criteria_have_next_action():
    for c in _AUDIT.by_status(FinishLineStatus.GAP):
        assert c.next_action, f"{c.criterion_id} GAP but missing next_action"


def test_synthesis_http_endpoint_is_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(FinishLineStatus.READY)}
    assert "synthesis_http_endpoint" in ids


def test_synthesis_owner_narrative_is_gap():
    ids = {c.criterion_id for c in _AUDIT.by_status(FinishLineStatus.GAP)}
    assert "synthesis_owner_narrative" in ids


# ---------------------------------------------------------------------------
# BLOCKED criteria
# ---------------------------------------------------------------------------

def test_blocked_criteria_have_blocker_reason():
    blocked = _AUDIT.by_status(FinishLineStatus.BLOCKED)
    assert blocked, "Expected at least one BLOCKED criterion"
    for c in blocked:
        assert c.blocker_reason, f"{c.criterion_id} BLOCKED but missing blocker_reason"


def test_no_api_mode_referenced_in_blocked():
    blocked = _AUDIT.by_status(FinishLineStatus.BLOCKED)
    any_no_api = any("NO-API" in (c.blocker_reason or "") for c in blocked)
    assert any_no_api, "Expected at least one BLOCKED criterion citing NO-API mode"


# ---------------------------------------------------------------------------
# OWNER_GATED criteria
# ---------------------------------------------------------------------------

def test_owner_gated_criteria_have_next_action():
    gated = _AUDIT.by_status(FinishLineStatus.OWNER_GATED)
    assert gated, "Expected at least one OWNER_GATED criterion"
    for c in gated:
        assert c.next_action, f"{c.criterion_id} OWNER_GATED but missing next_action"


def test_kg_production_mutation_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(FinishLineStatus.OWNER_GATED)}
    assert "kg_production_mutation" in ids


def test_kg_taxonomy_activation_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(FinishLineStatus.OWNER_GATED)}
    assert "kg_taxonomy_activation" in ids


# ---------------------------------------------------------------------------
# Synthesis criteria present
# ---------------------------------------------------------------------------

def test_teaching_synthesis_v1_is_ready():
    ready_ids = {c.criterion_id for c in _AUDIT.by_status(FinishLineStatus.READY)}
    assert "synthesis_teaching_v1" in ready_ids


def test_featured_genus_pool_is_ready():
    ready_ids = {c.criterion_id for c in _AUDIT.by_status(FinishLineStatus.READY)}
    assert "synthesis_featured_genus" in ready_ids


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_get_gaps_returns_only_gap_status():
    gaps = get_gaps()
    for c in gaps:
        assert c.status == FinishLineStatus.GAP


def test_get_criteria_by_status_ready():
    ready = get_criteria_by_status(FinishLineStatus.READY)
    assert all(c.status == FinishLineStatus.READY for c in ready)


def test_get_next_actions_non_empty():
    actions = get_next_actions()
    assert actions, "Expected at least one actionable next step"


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["area"]
        assert action["title"]
        assert action["status"]
        assert action["next_action"]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "calyx-owner-finish-line/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        d = c.to_dict()
        assert json.dumps(d)  # must not raise


def test_json_contains_no_credential_fields():
    output = _AUDIT.serialize_as_json().lower()
    forbidden = ["password", "secret", "api_key", "token", "private_key", "credential"]
    for word in forbidden:
        assert word not in output, f"Credential field '{word}' found in JSON output"


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    coordinate_keys = ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']
    for key in coordinate_keys:
        assert key not in output, f"Coordinate key '{key}' found in JSON output"


# ---------------------------------------------------------------------------
# Criterion-level structure
# ---------------------------------------------------------------------------

def test_all_criteria_have_criterion_id():
    for c in FINISH_LINE_CRITERIA:
        assert c.criterion_id, "criterion_id must not be empty"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in FINISH_LINE_CRITERIA]
    assert len(ids) == len(set(ids)), "Duplicate criterion_id detected"


def test_all_criteria_have_area():
    for c in FINISH_LINE_CRITERIA:
        assert c.area, f"{c.criterion_id}: area must not be empty"


def test_all_criteria_have_valid_status():
    valid = {
        FinishLineStatus.READY,
        FinishLineStatus.GAP,
        FinishLineStatus.BLOCKED,
        FinishLineStatus.OWNER_GATED,
    }
    for c in FINISH_LINE_CRITERIA:
        assert c.status in valid, f"{c.criterion_id}: invalid status '{c.status}'"


def test_all_criteria_have_authoritative_module():
    for c in FINISH_LINE_CRITERIA:
        assert c.authoritative_module, f"{c.criterion_id}: authoritative_module required"


def test_all_criteria_have_title():
    for c in FINISH_LINE_CRITERIA:
        assert c.title, f"{c.criterion_id}: title must not be empty"


# ---------------------------------------------------------------------------
# Audit counts realistic
# ---------------------------------------------------------------------------

def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 8


def test_audit_has_gap_items():
    assert _AUDIT.gap_count() >= 1


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_audit_has_owner_gated_items():
    assert _AUDIT.owner_gated_count() >= 1
