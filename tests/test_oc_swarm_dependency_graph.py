from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_dependency_graph", ROOT / "scripts" / "oc_swarm_dependency_graph.py"
)
assert SPEC is not None and SPEC.loader is not None
deps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deps)


def issue(number, *, body="", state="OPEN", labels=()):
    return {
        "number": number,
        "body": body,
        "state": state,
        "labels": list(labels),
    }


def test_explicit_dependencies_are_parsed_deterministically():
    row = issue(10, body="OC-SWARM-DEPENDS-ON: #3, #2, #3")
    assert deps.dependencies(row) == [2, 3]


def test_closed_dependency_unlocks_candidate():
    graph = deps.build_dependency_graph(
        [
            issue(1, state="CLOSED"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["ready"] is True
    assert graph["status"][2]["unsatisfied"] == []


def test_done_label_unlocks_candidate_even_if_issue_remains_open():
    graph = deps.build_dependency_graph(
        [
            issue(1, labels=("oc-done",)),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["ready"] is True


def test_open_dependency_blocks_candidate():
    graph = deps.build_dependency_graph(
        [
            issue(1),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["ready"] is False
    assert graph["status"][2]["unsatisfied"] == [1]


def test_missing_dependency_fails_closed():
    graph = deps.build_dependency_graph(
        [issue(2, body="OC-SWARM-DEPENDS-ON: #9999")]
    )
    assert graph["status"][2]["ready"] is False
    assert graph["status"][2]["missing"] == [9999]


def test_dependency_cycle_fails_closed():
    graph = deps.build_dependency_graph(
        [
            issue(1, body="OC-SWARM-DEPENDS-ON: #2"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["cycle_nodes"] == [1, 2]
    assert graph["status"][1]["ready"] is False
    assert graph["status"][2]["ready"] is False


def test_filter_ready_candidates_reports_block_reason():
    graph = deps.build_dependency_graph(
        [
            issue(1),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
            issue(3),
        ]
    )
    ready, blocked = deps.filter_ready_candidates(
        [{"number": 2}, {"number": 3}], graph
    )
    assert ready == [{"number": 3}]
    assert blocked[0]["issue_number"] == 2
    assert blocked[0]["reason"] == "dependency-blocked"
