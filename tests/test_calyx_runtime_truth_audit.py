"""Tests for Calyx runtime truth audit (Approved Task Priority 11).

Proves:
- All runtime truth criteria are present and serializable
- READY criteria have non-empty evidence and no gap_description
- GAP/BLOCKED/OWNER_GATED invariants
- All 6 runtime areas covered (routes/provider/persistence/degraded/orchestrator/security)
- no_auto_publication and no_production_mutation are always True
- JSON output contains no credentials or coordinate fields
"""

from __future__ import annotations

import json

from app.scientific_adapter_lab.calyx_runtime_truth_audit import (
    RUNTIME_TRUTH_CRITERIA,
    RuntimeTruthStatus,
    get_calyx_runtime_truth_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_calyx_runtime_truth_audit()
_DICT = _AUDIT.to_dict()


# ---------------------------------------------------------------------------
# Schema / structure
# ---------------------------------------------------------------------------

def test_schema_version_present():
    assert _DICT["schema_version"] == "calyx-runtime-truth-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"]
    assert len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(RUNTIME_TRUTH_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(RUNTIME_TRUTH_CRITERIA)


# ---------------------------------------------------------------------------
# READY criteria
# ---------------------------------------------------------------------------

def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(RuntimeTruthStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but has no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(RuntimeTruthStatus.READY):
        assert c.gap_description is None, f"{c.criterion_id} is READY but has gap_description"


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(RuntimeTruthStatus.READY):
        assert c.blocker_reason is None, f"{c.criterion_id} is READY but has blocker_reason"


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(RuntimeTruthStatus.READY):
        assert c.next_action is None, f"{c.criterion_id} is READY but has next_action"


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


# ---------------------------------------------------------------------------
# GAP criteria
# ---------------------------------------------------------------------------

def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(RuntimeTruthStatus.GAP):
        assert c.gap_description, f"{c.criterion_id} GAP but missing gap_description"


def test_gap_criteria_have_next_action():
    for c in _AUDIT.by_status(RuntimeTruthStatus.GAP):
        assert c.next_action, f"{c.criterion_id} GAP but missing next_action"


def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


# ---------------------------------------------------------------------------
# BLOCKED criteria
# ---------------------------------------------------------------------------

def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(RuntimeTruthStatus.BLOCKED):
        assert c.blocker_reason, f"{c.criterion_id} BLOCKED but missing blocker_reason"


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_api_cited_in_blocked():
    blocked = _AUDIT.by_status(RuntimeTruthStatus.BLOCKED)
    any_no_api = any("NO-API" in (c.blocker_reason or "") for c in blocked)
    assert any_no_api, "Expected at least one BLOCKED criterion citing NO-API mode"


# ---------------------------------------------------------------------------
# OWNER_GATED criteria
# ---------------------------------------------------------------------------

def test_owner_gated_criteria_have_next_action():
    gated = _AUDIT.by_status(RuntimeTruthStatus.OWNER_GATED)
    assert gated, "Expected at least one OWNER_GATED criterion"
    for c in gated:
        assert c.next_action, f"{c.criterion_id} OWNER_GATED but missing next_action"


def test_production_activation_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.OWNER_GATED)}
    assert "security_no_autonomous_production" in ids


# ---------------------------------------------------------------------------
# Area coverage
# ---------------------------------------------------------------------------

EXPECTED_AREAS = {"routes", "provider", "persistence", "degraded", "orchestrator", "security"}


def test_all_areas_covered():
    actual = {c.area for c in RUNTIME_TRUTH_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from runtime truth audit"


def test_routes_area_has_criteria():
    assert len(get_criteria_by_area("routes")) >= 3


def test_provider_area_has_criteria():
    assert len(get_criteria_by_area("provider")) >= 3


def test_persistence_area_has_criteria():
    assert len(get_criteria_by_area("persistence")) >= 2


def test_degraded_area_has_criteria():
    assert len(get_criteria_by_area("degraded")) >= 3


def test_orchestrator_area_has_criteria():
    assert len(get_criteria_by_area("orchestrator")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


# ---------------------------------------------------------------------------
# Key criteria present
# ---------------------------------------------------------------------------

def test_synthesis_endpoint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "routes_synthesis_endpoint" in ids


def test_capabilities_truthful_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "routes_capabilities_truthful" in ids


def test_no_api_mode_truthful_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "provider_no_api_mode_truthful" in ids


def test_provider_secret_non_exposure_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "provider_secret_non_exposure" in ids


def test_persistence_dual_mode_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "persistence_dual_mode" in ids


def test_degraded_synthesis_unavailable_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "degraded_synthesis_unavailable" in ids


def test_agent_gateway_runtime_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RuntimeTruthStatus.READY)}
    assert "security_agent_gateway_runtime" in ids


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == RuntimeTruthStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(RuntimeTruthStatus.READY):
        assert c.status == RuntimeTruthStatus.READY


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["area"]
        assert action["title"]
        assert action["status"]
        assert action["next_action"]


def test_get_next_actions_non_empty():
    assert get_next_actions(), "Expected at least one actionable next step"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "calyx-runtime-truth-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        d = c.to_dict()
        assert json.dumps(d)


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    forbidden_keys = ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']
    for key in forbidden_keys:
        assert key not in output, f"Credential key {key!r} found in JSON output"


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']:
        assert key not in output, f"Coordinate key {key!r} found in JSON output"


# ---------------------------------------------------------------------------
# Criterion-level structure
# ---------------------------------------------------------------------------

def test_all_criteria_have_criterion_id():
    for c in RUNTIME_TRUTH_CRITERIA:
        assert c.criterion_id


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in RUNTIME_TRUTH_CRITERIA]
    assert len(ids) == len(set(ids)), "Duplicate criterion_id detected"


def test_all_criteria_have_area():
    for c in RUNTIME_TRUTH_CRITERIA:
        assert c.area, f"{c.criterion_id}: area must not be empty"


def test_all_criteria_have_valid_status():
    valid = {RuntimeTruthStatus.READY, RuntimeTruthStatus.GAP,
             RuntimeTruthStatus.BLOCKED, RuntimeTruthStatus.OWNER_GATED}
    for c in RUNTIME_TRUTH_CRITERIA:
        assert c.status in valid, f"{c.criterion_id}: invalid status '{c.status}'"


def test_all_criteria_have_authoritative_module():
    for c in RUNTIME_TRUTH_CRITERIA:
        assert c.authoritative_module, f"{c.criterion_id}: authoritative_module required"


def test_all_criteria_have_title():
    for c in RUNTIME_TRUTH_CRITERIA:
        assert c.title, f"{c.criterion_id}: title must not be empty"


def test_all_criteria_have_evidence():
    for c in RUNTIME_TRUTH_CRITERIA:
        assert c.evidence, f"{c.criterion_id}: evidence must not be empty"
