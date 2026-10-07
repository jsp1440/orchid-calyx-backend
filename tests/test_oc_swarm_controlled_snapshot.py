from __future__ import annotations

import copy

import pytest

from scripts.oc_swarm_controlled_snapshot import (
    build_controlled_snapshot,
    parse_issue_numbers,
)
from scripts.oc_swarm_controller import build_swarm_plan


def _issue(number: int, lane: str, *, dependency: int | None = None) -> dict:
    dependency_marker = f"\nOC-SWARM-DEPENDS-ON: #{dependency}" if dependency else ""
    return {
        "number": number,
        "title": f"[R1 controlled test] {lane} validation",
        "body": (
            "OC-R1-CONTROLLED-TEST: true\n"
            f"OC-MODULE-LANE: {lane}\n"
            "OC-SWARM-PROVIDER-FREE: validate\n"
            "OC-SWARM-DISPOSITION: done\n"
            "OC-SWARM-READS: control-plane\n"
            "OC-SWARM-VALIDATE: control-plane-compiles"
            f"{dependency_marker}"
        ),
        "labels": ["oc-queued", "oc-r1-controlled-test"],
        "state": "OPEN",
    }


def test_controlled_snapshot_contains_only_explicit_independent_test_lanes() -> None:
    snapshot = {
        "issues": [
            _issue(10, "literature"),
            _issue(11, "frontend-ux"),
            _issue(12, "infrastructure-federation", dependency=10),
            {"number": 999, "title": "Unrelated queued issue", "labels": ["oc-queued"], "state": "OPEN"},
        ],
        "pull_requests": [{"number": 42}],
    }

    isolated = build_controlled_snapshot(snapshot, [10, 11, 12])

    assert [issue["number"] for issue in isolated["issues"]] == [10, 11, 12]
    assert isolated["pull_requests"] == []
    assert snapshot["issues"][-1]["number"] == 999
    assert snapshot["pull_requests"] == [{"number": 42}]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda issue: issue.update(title="uncontrolled title"), "title prefix"),
        (lambda issue: issue.update(body=issue["body"].replace("OC-R1-CONTROLLED-TEST: true\n", "")), "marker"),
        (
            lambda issue: issue.update(labels=["oc-running", "oc-r1-controlled-test"]),
            "exclusively queued",
        ),
        (
            lambda issue: issue.update(labels=["oc-queued"]),
            "isolating test label",
        ),
        (
            lambda issue: issue.update(body=issue["body"].replace("control-plane-compiles", "arbitrary-shell")),
            "registered control-plane-compiles",
        ),
        (lambda issue: issue.update(body=issue["body"].replace("OC-MODULE-LANE: literature", "OC-MODULE-LANE: taxonomy")), "allowed non-scientific lane"),
        (
            lambda issue: issue.update(body=issue["body"] + "\nOC-SWARM-DISPOSITION: owner-gate"),
            "declare done only from validation evidence",
        ),
        (
            lambda issue: issue.update(
                body=issue["body"].replace(
                    "OC-SWARM-READS: control-plane", "OC-SWARM-WRITES: control-plane"
                )
            ),
            "only the control-plane read resource",
        ),
    ],
)
def test_controlled_snapshot_rejects_scope_or_execution_changes(mutate, message: str) -> None:
    first = _issue(10, "literature")
    mutate(first)
    snapshot = {"issues": [first, _issue(11, "frontend-ux")]}

    with pytest.raises(ValueError, match=message):
        build_controlled_snapshot(snapshot, [10, 11])


def test_controlled_snapshot_rejects_dependencies_outside_allowlist() -> None:
    snapshot = {"issues": [_issue(10, "literature", dependency=99), _issue(11, "frontend-ux")]}

    with pytest.raises(ValueError, match="outside the allowlist"):
        build_controlled_snapshot(snapshot, [10, 11])


def test_controlled_snapshot_rejects_duplicate_or_missing_targets() -> None:
    snapshot = {"issues": [_issue(10, "literature"), _issue(11, "frontend-ux")]}

    with pytest.raises(ValueError, match="appears more than once"):
        build_controlled_snapshot({"issues": snapshot["issues"] + [copy.deepcopy(snapshot["issues"][0])]}, [10, 11])
    with pytest.raises(ValueError, match="missing"):
        build_controlled_snapshot(snapshot, [10, 12])


def test_controlled_snapshot_keeps_completed_dependencies_for_refill() -> None:
    completed = _issue(10, "literature")
    completed["labels"] = ["oc-done", "oc-r1-controlled-test"]
    dependent = _issue(12, "infrastructure-federation", dependency=10)
    dependent["labels"].append("oc-r1-controlled-test")

    isolated = build_controlled_snapshot(
        {"issues": [completed, _issue(11, "frontend-ux"), dependent]},
        [10, 11, 12],
    )

    assert [issue["number"] for issue in isolated["issues"]] == [10, 11, 12]


def test_controlled_snapshot_plans_two_lanes_then_dependency_refill() -> None:
    isolated = build_controlled_snapshot(
        {
            "issues": [
                _issue(10, "literature"),
                _issue(11, "frontend-ux"),
                _issue(12, "infrastructure-federation", dependency=10),
            ]
        },
        [10, 11, 12],
    )

    plan = build_swarm_plan(isolated, worker_slots=2, provider_free_only=True)

    assert plan["selected_numbers"] == [10, 11]
    assert plan["launch_count"] == 2
    assert plan["refill_recommended"] is True
    assert [row["issue_number"] for row in plan["dependency_suppressed"]] == [12]

    completed_first = _issue(10, "literature")
    completed_first["labels"] = ["oc-done", "oc-r1-controlled-test"]
    completed_second = _issue(11, "frontend-ux")
    completed_second["labels"] = ["oc-done", "oc-r1-controlled-test"]
    refill_issue = _issue(12, "infrastructure-federation", dependency=10)
    refill_issue["labels"].append("oc-r1-controlled-test")
    refilled = build_controlled_snapshot(
        {"issues": [completed_first, completed_second, refill_issue]},
        [10, 11, 12],
    )
    refill_plan = build_swarm_plan(refilled, worker_slots=2, provider_free_only=True)

    assert refill_plan["selected_numbers"] == [12]
    assert refill_plan["launch_count"] == 1


@pytest.mark.parametrize(
    "value",
    ["", "1", "1,2,3,4", "1,1", "0,2", "1, nope"],
)
def test_controlled_issue_number_list_is_bounded_and_unambiguous(value: str) -> None:
    with pytest.raises(ValueError):
        parse_issue_numbers(value)


def test_controlled_issue_number_list_accepts_two_or_three_distinct_numbers() -> None:
    assert parse_issue_numbers("10, 11") == [10, 11]
    assert parse_issue_numbers("10,11,12") == [10, 11, 12]
