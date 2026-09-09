from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_resource_locks", ROOT / "scripts" / "oc_swarm_resource_locks.py"
)
assert SPEC is not None and SPEC.loader is not None
locks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(locks)


def issue(number, title, body="", labels=None):
    return {"number": number, "title": title, "body": body, "labels": labels or []}


def test_explicit_markers_override_inference():
    claim = locks.infer_resources(
        issue(
            1,
            "Taxonomy and Atlas refactor",
            "OC-SWARM-READS: taxonomy\nOC-SWARM-WRITES: atlas, geospatial",
        ),
        "L2",
    )
    assert claim == {"reads": ["taxonomy"], "writes": ["atlas", "geospatial"]}


def test_same_lane_independent_resources_do_not_conflict():
    literature = locks.infer_resources(issue(1, "Literature provenance resolver"), "L3")
    images = locks.infer_resources(issue(2, "Image provenance contract"), "L3")
    assert "literature" in literature["writes"]
    assert "images" in images["writes"]
    assert locks.conflicts(literature, images) == []


def test_write_write_conflict_blocks():
    left = {"reads": [], "writes": ["taxonomy"]}
    right = {"reads": [], "writes": ["taxonomy"]}
    assert locks.conflicts(left, right) == ["taxonomy"]


def test_read_read_is_parallel_safe():
    left = {"reads": ["taxonomy"], "writes": []}
    right = {"reads": ["taxonomy"], "writes": []}
    assert locks.conflicts(left, right) == []


def test_read_write_conflict_blocks():
    left = {"reads": ["taxonomy"], "writes": []}
    right = {"reads": [], "writes": ["taxonomy"]}
    assert locks.conflicts(left, right) == ["taxonomy"]


def test_unclassified_work_falls_back_to_coarse_lane_lock():
    claim = locks.infer_resources(issue(1, "Completely novel subsystem"), "L4")
    assert claim == {"reads": [], "writes": ["lane-l4"]}


def test_control_plane_is_exclusive():
    claim = locks.infer_resources(issue(1, "Scheduler queue orchestration repair"), "L5")
    assert claim == {"reads": [], "writes": ["control-plane"]}


def test_selection_suppresses_only_conflicting_candidate():
    active = [{"issue_number": 9, "lane_id": "L2", "reads": [], "writes": ["taxonomy"]}]
    candidates = [
        (
            issue(10, "Taxonomy resolver"),
            "L2",
            {"number": 10, "priority": 0, "repair": False},
        ),
        (
            issue(11, "Image provenance contract"),
            "L3",
            {"number": 11, "priority": 1, "repair": False},
        ),
    ]
    selected, suppressed = locks.select_with_resource_locks(candidates, active_locks=active, capacity=2)
    assert [row["issue_number"] for row in selected] == [11]
    assert suppressed[0]["issue_number"] == 10
    assert suppressed[0]["reason"] == "resource-lock-conflict"
    assert suppressed[0]["blockers"][0]["resources"] == ["taxonomy"]
