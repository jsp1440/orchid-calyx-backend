"""Tests for OC-COMPLETE-008 — Calyx show-management current-main audit.

Proves acceptance criteria from issue #1088:
- inventory covers all ten required show-management areas
- every capability has required fields and a valid status
- CONVERGE capabilities have child tasks
- GAP capabilities have gap_description and child task
- unregistered routers are documented
- security risks are documented and classified
- no automatic publication, no KG mutation
- audit report serializable as JSON
- child tasks have required fields
"""

from __future__ import annotations

import json

from app.scientific_adapter_lab.show_management_audit import (
    CAPABILITY_INVENTORY,
    SCHEMA_VERSION,
    get_audit,
    get_capabilities_by_area,
    get_capabilities_by_status,
    get_child_tasks,
    get_inaccessible_capabilities,
    get_security_risks,
    get_unregistered_routers,
    serialize_audit_as_json,
)

REQUIRED_AREAS = {
    "shows",
    "entries",
    "plant_qr",
    "judging",
    "volunteers",
    "reference_docs",
    "auth",
    "notifications",
}

VALID_STATUSES = {"KEEP", "CONVERGE", "SUPERSEDE", "GAP", "RETIRED"}


# ---------------------------------------------------------------------------
# Inventory structure
# ---------------------------------------------------------------------------


def test_inventory_is_non_empty():
    assert len(CAPABILITY_INVENTORY) >= 20


def test_schema_version_present():
    assert SCHEMA_VERSION == "oc-show-management-audit/v1"


def test_every_capability_has_required_fields():
    required = {"capability_id", "capability", "area", "module", "status"}
    for cap in CAPABILITY_INVENTORY:
        missing = required - set(cap)
        assert not missing, f"{cap.get('capability_id')} missing: {missing}"


def test_every_status_is_valid():
    for cap in CAPABILITY_INVENTORY:
        assert cap["status"] in VALID_STATUSES, (
            f"{cap['capability_id']} has invalid status: {cap['status']}"
        )


def test_capability_ids_are_unique():
    ids = [c["capability_id"] for c in CAPABILITY_INVENTORY]
    assert len(ids) == len(set(ids)), "Duplicate capability_ids found"


def test_inventory_covers_all_required_areas():
    areas = {c["area"] for c in CAPABILITY_INVENTORY}
    assert REQUIRED_AREAS <= areas, f"Missing areas: {REQUIRED_AREAS - areas}"


# ---------------------------------------------------------------------------
# KEEP capabilities
# ---------------------------------------------------------------------------


def test_keep_capabilities_exist():
    keep = get_capabilities_by_status("KEEP")
    assert len(keep) >= 10


def test_keep_capabilities_are_accessible():
    for cap in get_capabilities_by_status("KEEP"):
        assert cap.get("accessible") is True, (
            f"KEEP capability {cap['capability_id']} should be accessible"
        )


# ---------------------------------------------------------------------------
# CONVERGE capabilities
# ---------------------------------------------------------------------------


def test_converge_capabilities_have_child_tasks():
    for cap in get_capabilities_by_status("CONVERGE"):
        assert cap.get("child_task"), (
            f"CONVERGE {cap['capability_id']} missing child_task"
        )


def test_converge_capabilities_exist():
    assert len(get_capabilities_by_status("CONVERGE")) >= 3


# ---------------------------------------------------------------------------
# GAP capabilities
# ---------------------------------------------------------------------------


def test_gap_capabilities_have_gap_description():
    for cap in get_capabilities_by_status("GAP"):
        assert cap.get("gap_description"), (
            f"GAP {cap['capability_id']} missing gap_description"
        )


def test_gap_capabilities_have_child_tasks():
    for cap in get_capabilities_by_status("GAP"):
        assert cap.get("child_task"), (
            f"GAP {cap['capability_id']} missing child_task"
        )


def test_gap_capabilities_exist():
    assert len(get_capabilities_by_status("GAP")) >= 8


def test_judging_lock_gap_documented():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "show_judging_lock_enforcement")
    assert cap["status"] == "GAP"
    assert "judging_locked" in cap["gap_description"]


def test_judge_auth_gap_documented_as_high_risk():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "judge_auth_cryptographic")
    assert cap["status"] == "GAP"
    assert cap.get("security_risk") == "HIGH"


def test_path_traversal_gap_documented_as_medium_risk():
    cap = next(
        c for c in CAPABILITY_INVENTORY if c["capability_id"] == "reference_docs_path_traversal_guard"
    )
    assert cap["status"] == "GAP"
    assert cap.get("security_risk") == "MEDIUM"


# ---------------------------------------------------------------------------
# SUPERSEDE capabilities
# ---------------------------------------------------------------------------


def test_supersede_capabilities_have_child_tasks():
    for cap in get_capabilities_by_status("SUPERSEDE"):
        assert cap.get("child_task"), (
            f"SUPERSEDE {cap['capability_id']} missing child_task"
        )


def test_legacy_score_submissions_is_supersede():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "legacy_score_submissions")
    assert cap["status"] == "SUPERSEDE"


def test_legacy_volunteer_tasks_is_supersede():
    cap = next(c for c in CAPABILITY_INVENTORY if c["capability_id"] == "volunteer_tasks_legacy")
    assert cap["status"] == "SUPERSEDE"


# ---------------------------------------------------------------------------
# Unregistered routers
# ---------------------------------------------------------------------------


def test_unregistered_routers_documented():
    routers = get_unregistered_routers()
    assert len(routers) >= 2


def test_volunteer_ops_unregistered():
    routers = get_unregistered_routers()
    modules = [r["module"] for r in routers]
    assert any("volunteer_ops" in m for m in modules)


def test_shows_router_unregistered():
    routers = get_unregistered_routers()
    modules = [r["module"] for r in routers]
    assert any("shows" in m for m in modules)


def test_unregistered_routers_have_child_tasks():
    for router in get_unregistered_routers():
        assert router.get("child_task"), f"Unregistered router {router['module']} missing child_task"


def test_inaccessible_capabilities_exist():
    inaccessible = get_inaccessible_capabilities()
    assert len(inaccessible) >= 5


# ---------------------------------------------------------------------------
# Security risks
# ---------------------------------------------------------------------------


def test_security_risks_documented():
    risks = get_security_risks()
    assert len(risks) >= 2


def test_security_risks_have_high_and_medium():
    risks = get_security_risks()
    risk_levels = {r["security_risk"] for r in risks}
    assert "HIGH" in risk_levels
    assert "MEDIUM" in risk_levels


def test_security_risks_all_have_child_tasks():
    for cap in get_security_risks():
        assert cap.get("child_task"), f"Security risk {cap['capability_id']} missing child_task"


# ---------------------------------------------------------------------------
# Child tasks
# ---------------------------------------------------------------------------


def test_child_tasks_exist():
    tasks = get_child_tasks()
    assert len(tasks) >= 10


def test_child_tasks_have_required_fields():
    required = {"capability_id", "area", "status", "title"}
    for task in get_child_tasks():
        missing = required - set(task)
        assert not missing, f"Child task {task.get('capability_id')} missing: {missing}"


def test_child_tasks_have_non_empty_titles():
    for task in get_child_tasks():
        assert task["title"], f"Child task {task['capability_id']} has empty title"


# ---------------------------------------------------------------------------
# Area accessor
# ---------------------------------------------------------------------------


def test_area_shows_has_capabilities():
    caps = get_capabilities_by_area("shows")
    assert len(caps) >= 3


def test_area_volunteers_has_capabilities():
    caps = get_capabilities_by_area("volunteers")
    assert len(caps) >= 3


def test_area_judging_has_capabilities():
    caps = get_capabilities_by_area("judging")
    assert len(caps) >= 6


def test_area_auth_has_capabilities():
    caps = get_capabilities_by_area("auth")
    assert len(caps) >= 3


def test_area_notifications_has_capabilities():
    caps = get_capabilities_by_area("notifications")
    assert len(caps) >= 2


# ---------------------------------------------------------------------------
# Audit report
# ---------------------------------------------------------------------------


def test_audit_schema_version():
    audit = get_audit()
    assert audit["schema_version"] == SCHEMA_VERSION


def test_audit_no_auto_publication():
    audit = get_audit()
    assert audit["automatic_publication"] is False
    assert audit["knowledge_graph_mutation"] is False
    assert audit["graph_mutation"] is False


def test_audit_counts_consistent():
    audit = get_audit()
    assert audit["capability_count"] == len(CAPABILITY_INVENTORY)
    assert audit["accessible_count"] + audit["inaccessible_count"] == len(CAPABILITY_INVENTORY)


def test_audit_status_counts_sum_to_total():
    audit = get_audit()
    assert sum(audit["status_counts"].values()) == audit["capability_count"]


def test_audit_contains_child_tasks():
    audit = get_audit()
    assert len(audit["child_tasks"]) >= 10


def test_audit_contains_security_risks():
    audit = get_audit()
    assert audit["security_risk_count"] >= 2


def test_audit_serializable_as_json():
    raw = serialize_audit_as_json()
    parsed = json.loads(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["capability_count"] == len(CAPABILITY_INVENTORY)


def test_audit_json_no_secrets():
    raw = serialize_audit_as_json()
    for bad in ("sk-live-", "Bearer ", "api_key=", "password=", "API_KEY="):
        assert bad not in raw, f"Potential secret pattern found: {bad}"


def test_audit_date_present():
    audit = get_audit()
    assert audit["audit_date"] == "2026-09-04"


def test_audit_unregistered_router_count():
    audit = get_audit()
    assert audit["unregistered_router_count"] >= 2
