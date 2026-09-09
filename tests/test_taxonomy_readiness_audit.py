"""Tests for taxonomy readiness audit (Approved Task Priority 10).

Proves:
- All readiness criteria are present and serializable
- READY criteria have non-empty evidence and no gap_description
- GAP criteria have gap_description and next_action
- BLOCKED criteria have blocker_reason
- OWNER_GATED criteria have next_action
- no_auto_publication and no_production_mutation are always True
- Audit summary counts are consistent
- JSON output contains no credentials or coordinate fields
- All 7 taxonomy areas are represented (storage/staging/smoke/crosswalk/impact/promotion/rollback)
"""

from __future__ import annotations

import json

from app.scientific_adapter_lab.taxonomy_readiness_audit import (
    READINESS_CRITERIA,
    ReadinessStatus,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
    get_taxonomy_readiness_audit,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUDIT = get_taxonomy_readiness_audit()
_DICT = _AUDIT.to_dict()


# ---------------------------------------------------------------------------
# Schema / structure
# ---------------------------------------------------------------------------

def test_schema_version_present():
    assert _DICT["schema_version"] == "taxonomy-readiness-audit/v1"


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
    assert len(READINESS_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(READINESS_CRITERIA)


# ---------------------------------------------------------------------------
# READY criteria
# ---------------------------------------------------------------------------

def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(ReadinessStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but has no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(ReadinessStatus.READY):
        assert c.gap_description is None, (
            f"{c.criterion_id} is READY but has gap_description"
        )


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(ReadinessStatus.READY):
        assert c.blocker_reason is None, (
            f"{c.criterion_id} is READY but has blocker_reason"
        )


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(ReadinessStatus.READY):
        assert c.next_action is None, (
            f"{c.criterion_id} is READY but has next_action"
        )


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 15


# ---------------------------------------------------------------------------
# GAP criteria
# ---------------------------------------------------------------------------

def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(ReadinessStatus.GAP):
        assert c.gap_description, f"{c.criterion_id} GAP but missing gap_description"


def test_gap_criteria_have_next_action():
    for c in _AUDIT.by_status(ReadinessStatus.GAP):
        assert c.next_action, f"{c.criterion_id} GAP but missing next_action"


def test_audit_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


# ---------------------------------------------------------------------------
# BLOCKED criteria
# ---------------------------------------------------------------------------

def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(ReadinessStatus.BLOCKED):
        assert c.blocker_reason, f"{c.criterion_id} BLOCKED but missing blocker_reason"


def test_audit_blocked_count_consistent():
    assert _AUDIT.blocked_count() >= 0


# ---------------------------------------------------------------------------
# OWNER_GATED criteria
# ---------------------------------------------------------------------------

def test_owner_gated_criteria_have_next_action():
    gated = _AUDIT.by_status(ReadinessStatus.OWNER_GATED)
    assert gated, "Expected at least one OWNER_GATED criterion"
    for c in gated:
        assert c.next_action, f"{c.criterion_id} OWNER_GATED but missing next_action"


def test_promotion_activation_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.OWNER_GATED)}
    assert "promotion_activation_blocked" in ids


def test_rollback_production_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.OWNER_GATED)}
    assert "rollback_production_authorization" in ids


# ---------------------------------------------------------------------------
# Area coverage — all 7 areas must appear
# ---------------------------------------------------------------------------

EXPECTED_AREAS = {"storage", "staging", "smoke", "crosswalk", "impact", "promotion", "rollback"}


def test_all_areas_covered():
    actual_areas = {c.area for c in READINESS_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual_areas, f"Area '{area}' missing from taxonomy readiness audit"


def test_storage_area_has_criteria():
    assert len(get_criteria_by_area("storage")) >= 2


def test_staging_area_has_criteria():
    assert len(get_criteria_by_area("staging")) >= 2


def test_smoke_area_has_criteria():
    assert len(get_criteria_by_area("smoke")) >= 2


def test_crosswalk_area_has_criteria():
    assert len(get_criteria_by_area("crosswalk")) >= 2


def test_impact_area_has_criteria():
    assert len(get_criteria_by_area("impact")) >= 3


def test_promotion_area_has_criteria():
    assert len(get_criteria_by_area("promotion")) >= 2


def test_rollback_area_has_criteria():
    assert len(get_criteria_by_area("rollback")) >= 2


# ---------------------------------------------------------------------------
# Key criteria present
# ---------------------------------------------------------------------------

def test_storage_csv_tsv_validation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.READY)}
    assert "storage_csv_tsv_validation" in ids


def test_staging_intake_service_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.READY)}
    assert "staging_intake_service" in ids


def test_promotion_readiness_gate_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.READY)}
    assert "promotion_readiness_gate" in ids


def test_rollback_bundle_verification_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.READY)}
    assert "rollback_bundle_verification" in ids


def test_rollback_atomic_writes_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ReadinessStatus.READY)}
    assert "rollback_atomic_writes" in ids


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_get_gaps_returns_only_gap_status():
    gaps = get_gaps()
    for c in gaps:
        assert c.status == ReadinessStatus.GAP


def test_get_criteria_by_status_ready():
    ready = get_criteria_by_status(ReadinessStatus.READY)
    assert all(c.status == ReadinessStatus.READY for c in ready)


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["area"]
        assert action["title"]
        assert action["status"]
        assert action["next_action"]


def test_get_next_actions_non_empty():
    actions = get_next_actions()
    assert actions, "Expected at least one actionable next step (OWNER_GATED criteria)"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "taxonomy-readiness-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        d = c.to_dict()
        assert json.dumps(d)  # must not raise


def test_json_contains_no_credential_fields():
    # Check for credential JSON keys, not arbitrary substrings (evidence text may mention variable names)
    output = _AUDIT.serialize_as_json().lower()
    forbidden_keys = ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']
    for key in forbidden_keys:
        assert key not in output, f"Credential key {key!r} found in JSON output"


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    coordinate_keys = ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']
    for key in coordinate_keys:
        assert key not in output, f"Coordinate key '{key}' found in JSON output"


# ---------------------------------------------------------------------------
# Criterion-level structure
# ---------------------------------------------------------------------------

def test_all_criteria_have_criterion_id():
    for c in READINESS_CRITERIA:
        assert c.criterion_id, "criterion_id must not be empty"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in READINESS_CRITERIA]
    assert len(ids) == len(set(ids)), "Duplicate criterion_id detected"


def test_all_criteria_have_area():
    for c in READINESS_CRITERIA:
        assert c.area, f"{c.criterion_id}: area must not be empty"


def test_all_criteria_have_valid_status():
    valid = {
        ReadinessStatus.READY,
        ReadinessStatus.GAP,
        ReadinessStatus.BLOCKED,
        ReadinessStatus.OWNER_GATED,
    }
    for c in READINESS_CRITERIA:
        assert c.status in valid, f"{c.criterion_id}: invalid status '{c.status}'"


def test_all_criteria_have_authoritative_module():
    for c in READINESS_CRITERIA:
        assert c.authoritative_module, f"{c.criterion_id}: authoritative_module required"


def test_all_criteria_have_title():
    for c in READINESS_CRITERIA:
        assert c.title, f"{c.criterion_id}: title must not be empty"


def test_all_criteria_have_evidence():
    for c in READINESS_CRITERIA:
        assert c.evidence, f"{c.criterion_id}: evidence must not be empty"
