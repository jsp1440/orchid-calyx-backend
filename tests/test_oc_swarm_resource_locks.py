from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------
# Path-disjoint relaxation (fail closed)
# --------------------------------------------------------------------------


def paths_body(*paths, extra=""):
    listing = "".join(f"- `{p}`\n" for p in paths)
    return f"{extra}\nAllowed paths:\n{listing}"


def cand(number, title, body="", lane="L5", labels=None, enforced=True):
    # ``enforced`` mirrors the controller flag: the executor refuses writes
    # outside the declared Allowed paths (paid lane only).
    return (
        issue(number, title, body, labels),
        lane,
        {
            "number": number,
            "priority": number,
            "repair": False,
            "path_relaxation_executor": enforced,
        },
    )


def run(candidates, active=None, capacity=5):
    report = {}
    selected, suppressed = locks.select_with_resource_locks(
        candidates, active_locks=active or [], capacity=capacity, report=report
    )
    return [row["issue_number"] for row in selected], suppressed, report


def keyword_pair(left_paths, right_paths, left_extra="", right_extra=""):
    # Both titles hit the "control-plane" keyword, so today they serialize.
    return [
        cand(1, "Scheduler queue tweak A", paths_body(*left_paths, extra=left_extra)),
        cand(2, "Scheduler queue tweak B", paths_body(*right_paths, extra=right_extra)),
    ]


def test_baseline_without_paths_still_serializes_keyword_overlap():
    picked, suppressed, report = run(
        [cand(1, "Scheduler queue A"), cand(2, "Scheduler queue B")]
    )
    assert picked == [1]
    assert suppressed[0]["issue_number"] == 2
    assert suppressed[0]["reason"] == "resource-lock-conflict"
    assert report["path_disjoint_allowed"] == []
    assert report["serialized"][0]["issue_number"] == 2


def test_disjoint_directories_run_together_and_are_reported():
    picked, suppressed, report = run(keyword_pair(["app/a/x.py"], ["scripts/b/y.py"]))
    assert picked == [1, 2]
    assert suppressed == []
    allowed = report["path_disjoint_allowed"]
    assert len(allowed) == 1
    assert allowed[0]["issue_number"] == 2
    assert allowed[0]["with_issue_number"] == 1
    assert allowed[0]["resources"] == ["control-plane"]
    assert allowed[0]["paths"] == ["scripts/b/y.py"]
    assert allowed[0]["with_paths"] == ["app/a/x.py"]


def test_same_file_serializes():
    picked, suppressed, _ = run(keyword_pair(["app/a.py"], ["app/a.py"]))
    assert picked == [1]
    assert "paths-overlap" in suppressed[0]["path_checks"][0]["reason"]


def test_parent_child_serializes_both_directions():
    assert run(keyword_pair(["app"], ["app/x/y.py"]))[0] == [1]
    assert run(keyword_pair(["app/x/y.py"], ["app"]))[0] == [1]
    assert run(keyword_pair(["app/x/"], ["app/x/y.py"]))[0] == [1]


def test_shared_string_prefix_is_not_ancestry():
    # 'app/a' is a string prefix of 'app/ab' but not a path ancestor.
    assert run(keyword_pair(["app/a"], ["app/ab"]))[0] == [1, 2]
    assert run(keyword_pair(["app/ab/z.py"], ["app/a"]))[0] == [1, 2]
    assert run(keyword_pair(["app/a.py"], ["app/a.pyc"]))[0] == [1, 2]
    assert run(keyword_pair(["app/a"], ["app/a/b.py"]))[0] == [1]


def test_case_differences_are_treated_as_overlap():
    assert run(keyword_pair(["App/X.py"], ["app/x.py"]))[0] == [1]


def test_missing_or_empty_paths_serialize():
    one_sided = [
        cand(1, "Scheduler queue A", paths_body("app/a.py")),
        cand(2, "Scheduler queue B"),
    ]
    assert run(one_sided)[0] == [1]
    assert run(list(reversed(one_sided)))[0] == [2]
    empty = [
        cand(1, "Scheduler queue A", "Allowed paths:\n"),
        cand(2, "Scheduler queue B", paths_body("app/b.py")),
    ]
    assert run(empty)[0] == [1]


@pytest.mark.parametrize(
    "bad",
    [
        "../x.py",
        "app/../x.py",
        "/etc/passwd",
        ".",
        "/",
        "./app/x.py",
        "app//x.py",
        "app/./x.py",
        "app\\x.py",
        "app/*.py",
        "app/**",
        "app/x?.py",
        "app/[ab].py",
        "app/{a,b}.py",
        "~/x.py",
        "C:/x.py",
        "app/x y.py",
        "$HOME/x.py",
        "a" * 400,
    ],
)
def test_malformed_or_ambiguous_paths_serialize(bad):
    assert run(keyword_pair([bad], ["scripts/b/y.py"]))[0] == [1]
    assert run(keyword_pair(["scripts/b/y.py"], [bad]))[0] == [1]


def test_one_bad_entry_poisons_the_whole_set():
    assert run(keyword_pair(["app/a.py", "../b.py"], ["scripts/b.py"]))[0] == [1]


def test_duplicate_declarations_are_ambiguous():
    body = paths_body("app/a.py") + "\n" + paths_body("app/a2.py")
    pair = [
        cand(1, "Scheduler queue A", body),
        cand(2, "Scheduler queue B", paths_body("x/y.py")),
    ]
    assert run(pair)[0] == [1]


def test_oversized_path_set_serializes():
    many = [f"app/m{i}.py" for i in range(13)]
    assert run(keyword_pair(many, ["scripts/b.py"]))[0] == [1]
    assert run(keyword_pair(many[:12], ["scripts/b.py"]))[0] == [1, 2]


def test_explicit_exclusive_marker_stays_authoritative():
    marker = "OC-SWARM-WRITES: control-plane"
    assert run(keyword_pair(["app/a.py"], ["scripts/b.py"], left_extra=marker))[0] == [1]
    assert run(keyword_pair(["app/a.py"], ["scripts/b.py"], right_extra=marker))[0] == [1]
    assert run(keyword_pair(["app/a.py"], ["scripts/b.py"], marker, marker))[0] == [1]
    t = "OC-SWARM-WRITES: taxonomy"
    pair = [
        cand(1, "Taxonomy A", paths_body("app/a.py", extra=t)),
        cand(2, "Taxonomy B", paths_body("scripts/b.py", extra=t)),
    ]
    assert run(pair)[0] == [1]


def test_resource_label_stays_authoritative():
    pair = [
        cand(1, "x", paths_body("app/a.py"), labels=["oc-resource-atlas"]),
        cand(2, "y", paths_body("scripts/b.py"), labels=["oc-resource-atlas"]),
    ]
    assert run(pair)[0] == [1]
    mixed = [
        cand(1, "Atlas tour", paths_body("app/a.py")),
        cand(2, "y", paths_body("scripts/b.py"), labels=["oc-resource-atlas"]),
    ]
    assert run(mixed)[0] == [1]


def test_lane_fallback_with_disjoint_paths_is_relaxed():
    pair = [
        cand(1, "Completely novel subsystem", paths_body("app/a.py"), lane="L4"),
        cand(2, "Another novel subsystem", paths_body("scripts/b.py"), lane="L4"),
    ]
    assert run(pair)[0] == [1, 2]


def test_active_lock_without_path_data_still_blocks():
    legacy = [{"issue_number": 9, "lane_id": "L5", "reads": [], "writes": ["control-plane"]}]
    picked, suppressed, _ = run(
        [cand(2, "Scheduler queue B", paths_body("scripts/b.py"))], active=legacy
    )
    assert picked == []
    assert suppressed[0]["blockers"][0]["resources"] == ["control-plane"]


def test_active_lock_built_by_held_locks_carries_paths():
    held = locks.held_locks([(issue(9, "Scheduler queue A", paths_body("app/a.py")), "L5")])
    assert held[0].get("path_relaxation_executor") is None  # fail closed by default
    assert run([cand(2, "Scheduler queue B", paths_body("scripts/b.py"))], active=held)[0] == []
    held[0]["path_relaxation_executor"] = True
    assert run([cand(2, "Scheduler queue B", paths_body("scripts/b.py"))], active=held)[0] == [2]
    assert run([cand(2, "Scheduler queue B", paths_body("app/a.py"))], active=held)[0] == []


def test_non_overlapping_resources_unaffected_by_paths():
    pair = [
        cand(1, "Literature resolver", paths_body("app/a.py")),
        cand(2, "Image contract", paths_body("app/a.py")),
    ]
    picked, _, report = run(pair)
    assert picked == [1, 2]
    assert report["path_disjoint_allowed"] == []


def test_three_way_requires_all_conflicting_pairs_disjoint():
    trio = [
        cand(1, "Scheduler queue A", paths_body("app/a.py")),
        cand(2, "Scheduler queue B", paths_body("scripts/b.py")),
        cand(3, "Scheduler queue C", paths_body("scripts/b.py", "docs/c.md")),
    ]
    assert run(trio)[0] == [1, 2]
    assert run(trio, capacity=1)[0] == [1]


def test_capacity_is_still_the_only_cap():
    many = [cand(i, f"Scheduler queue {i}", paths_body(f"app/m{i}.py")) for i in range(1, 8)]
    assert run(many, capacity=3)[0] == [1, 2, 3]
    assert run(many, capacity=0)[0] == []


def test_read_read_parallel_and_read_write_blocked_unchanged():
    picked = run(
        [
            cand(1, "r1", "OC-SWARM-READS: taxonomy"),
            cand(2, "r2", "OC-SWARM-READS: taxonomy"),
            cand(3, "w", "OC-SWARM-WRITES: taxonomy"),
        ]
    )[0]
    assert picked == [1, 2]


def test_selection_is_deterministic_and_large_input_bounded():
    many = [cand(i, f"Scheduler queue {i}", paths_body(f"app/m{i}.py")) for i in range(1, 400)]
    assert run(many, capacity=10) == run(many, capacity=10)
    assert run(many, capacity=10)[0] == list(range(1, 11))
    huge_body = "Allowed paths:\n" + "".join(f"- `p{i}/x.py`\n" for i in range(50000))
    pair = [
        cand(999, "Scheduler queue base", paths_body("app/a.py")),
        cand(1000, "Scheduler queue huge", huge_body),
    ]
    assert run(pair)[0] == [999]


def test_report_explains_serialized_pairs():
    _, _, report = run(keyword_pair(["app/a.py"], ["app/a.py"]))
    row = report["serialized"][0]
    assert row["issue_number"] == 2
    assert row["blockers"][0]["issue_number"] == 1
    assert row["blockers"] == [{"issue_number": 1, "resources": ["control-plane"]}]
    assert row["path_checks"][0]["issue_number"] == 1
    assert row["path_checks"][0]["relaxed"] is False
    _, _, report = run(
        keyword_pair(["app/a.py"], ["scripts/b.py"], left_extra="OC-SWARM-WRITES: control-plane")
    )
    reason = report["serialized"][0]["path_checks"][0]["reason"]
    assert reason.startswith("explicit-resource-authoritative")


def test_parser_subset_agrees_with_worker_enforcement_parser():
    # Whatever the strict lock parser accepts, the executor's own parser must
    # read identically, so the lock reasons about the set the worker enforces.
    worker_spec = importlib.util.spec_from_file_location(
        "swarm_anthropic_direct_for_locks", ROOT / "scripts" / "swarm_anthropic_direct.py"
    )
    mod = importlib.util.module_from_spec(worker_spec)
    sys.modules[worker_spec.name] = mod
    worker_spec.loader.exec_module(mod)
    bodies = [
        paths_body("app/a.py", "scripts/b.py"),
        "intro\nAllowed paths: `app/a.py`, `tests/t.py`\nmore",
        "Allowed paths:\n- app/a.py\n- `docs/x.md` (note)\n\nprose",
        paths_body("app/a.py") + paths_body("app/b.py"),
    ]
    accepted = 0
    for body in bodies:
        mine = locks.parse_allowed_paths(body)
        if mine is not None:
            accepted += 1
            assert set(mine) == mod._parse_allowed_paths(body)
    assert accepted == 3


def test_unenforced_executor_is_never_relaxed_on_either_side():
    # provider-free / acquisition / unroutable work: disjoint declared paths do
    # not matter because its executor does not enforce them.
    for left, right in ((False, True), (True, False), (False, False)):
        pair = [
            cand(1, "Scheduler queue A", paths_body("app/a.py"), enforced=left),
            cand(2, "Scheduler queue B", paths_body("scripts/b.py"), enforced=right),
        ]
        picked, suppressed, _ = run(pair)
        assert picked == [1]
        reason = suppressed[0]["path_checks"][0]["reason"]
        assert reason.endswith("-executor-does-not-enforce-declared-paths")


def test_missing_or_truthy_non_true_flag_is_not_enforced():
    for flag in (None, 1, "yes"):
        a = cand(1, "Scheduler queue A", paths_body("app/a.py"))
        b = cand(2, "Scheduler queue B", paths_body("scripts/b.py"))
        if flag is None:
            del b[2]["path_relaxation_executor"]
        else:
            b[2]["path_relaxation_executor"] = flag
        assert run([a, b])[0] == [1]
    held = [{"issue_number": 9, "lane_id": "L5", "reads": [], "writes": ["control-plane"],
             "source": "keyword", "paths": ["app/a.py"]}]
    assert run([cand(2, "Scheduler queue B", paths_body("scripts/b.py"))], active=held)[0] == []
