from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_controller", ROOT / "scripts" / "oc_swarm_controller.py"
)
assert SPEC is not None and SPEC.loader is not None
swarm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(swarm)


class FakeScheduler:
    @staticmethod
    def build_plan(snapshot):
        return {
            "ranking": [
                {"number": 100, "lane_id": "L3", "priority": 0, "repair": False},
                {"number": 101, "lane_id": "L3", "priority": 1, "repair": False},
                {"number": 102, "lane_id": "L4", "priority": 2, "repair": True},
            ],
            "active_lanes": [],
            "eligible_count": 3,
            "suppressed": [],
            "generated_at": "2026-09-09T16:00:00Z",
        }


class FakeLocks:
    @staticmethod
    def held_locks(rows):
        return []

    @staticmethod
    def select_with_resource_locks(candidates, *, active_locks, capacity):
        selected = []
        for issue, lane_id, public in list(candidates)[:capacity]:
            selected.append(
                {
                    **public,
                    "issue_number": issue["number"],
                    "lane_id": lane_id,
                    "reads": [],
                    "writes": [f"resource-{issue['number']}"],
                }
            )
        return selected, []


class FakeDeps:
    @staticmethod
    def build_dependency_graph(issues):
        rows = list(issues)
        return {
            "edge_count": 1,
            "cycle_nodes": [],
            "status": {
                int(issue["number"]): {
                    "issue_number": int(issue["number"]),
                    "dependencies": [99] if int(issue["number"]) == 101 else [],
                    "ready": True,
                }
                for issue in rows
                if issue.get("number") is not None
            },
        }

    @staticmethod
    def filter_ready_candidates(ranked, graph):
        return list(ranked), []


def _loader(name, filename):
    if filename == "oc_portfolio_scheduler.py":
        return FakeScheduler
    if filename == "oc_swarm_resource_locks.py":
        return FakeLocks
    if filename == "oc_swarm_dependency_graph.py":
        return FakeDeps
    raise AssertionError(filename)


def _snapshot():
    return {
        "issues": [
            {"number": 99, "title": "Prior work", "body": "", "labels": ["oc-done"], "state": "CLOSED"},
            {"number": 100, "title": "Literature work", "body": "", "labels": ["oc-queued"], "state": "OPEN"},
            {"number": 101, "title": "Image work", "body": "OC-SWARM-DEPENDS-ON: #99", "labels": ["oc-queued"], "state": "OPEN"},
            {"number": 102, "title": "Atlas work", "body": "", "labels": ["oc-queued"], "state": "OPEN"},
        ]
    }


def test_swarm_plan_is_bounded_to_hard_max(monkeypatch):
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    plan = swarm.build_swarm_plan(_snapshot(), worker_slots=99)
    assert plan["effective_worker_slots"] == 12
    assert plan["launch_count"] == 3
    assert plan["schema"] == "oc.swarm-plan.v4"
    assert plan["safety"]["bounded"] is True
    assert plan["safety"]["resource_locking"] is True
    assert plan["safety"]["dependency_graph"] is True


def test_swarm_v4_can_schedule_two_workers_from_same_coarse_lane(monkeypatch):
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    plan = swarm.build_swarm_plan(_snapshot(), worker_slots=8)
    assert plan["selected_numbers"][:2] == [100, 101]
    assert plan["workers"][0]["lane_id"] == "L3"
    assert plan["workers"][1]["lane_id"] == "L3"
    assert plan["workers"][0]["writes"] != plan["workers"][1]["writes"]
    assert plan["workers"][1]["dependencies"] == [99]


def test_swarm_v4_refills_when_compatible_work_exceeds_current_capacity(monkeypatch):
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    plan = swarm.build_swarm_plan(_snapshot(), worker_slots=2)
    assert plan["launch_count"] == 2
    assert plan["waiting_count"] == 1
    assert plan["refill_recommended"] is True


def test_swarm_plan_strips_stabilization_freeze(monkeypatch):
    captured = {}

    class CapturingScheduler:
        @staticmethod
        def build_plan(snapshot):
            captured.update(snapshot)
            return {
                "ranking": [],
                "active_lanes": [],
                "eligible_count": 0,
                "suppressed": [],
                "generated_at": None,
            }

    def loader(name, filename):
        if filename == "oc_portfolio_scheduler.py":
            return CapturingScheduler
        if filename == "oc_swarm_resource_locks.py":
            return FakeLocks
        if filename == "oc_swarm_dependency_graph.py":
            return FakeDeps
        raise AssertionError(filename)

    monkeypatch.setattr(swarm, "_load_sibling", loader)
    plan = swarm.build_swarm_plan({"stabilization_issue": 1193, "issues": []}, worker_slots=8)
    assert "stabilization_issue" not in captured
    assert captured["max_active_lanes"] == 8
    assert plan["launch_count"] == 0


def test_worker_slots_must_be_positive(monkeypatch):
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    try:
        swarm.build_swarm_plan(_snapshot(), worker_slots=0)
    except ValueError as exc:
        assert ">= 1" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_provider_free_mode_hides_unmarked_queue_without_losing_dependencies(monkeypatch):
    captured = {}

    class CapturingScheduler:
        @staticmethod
        def build_plan(snapshot):
            captured.update(snapshot)
            marked = next(issue for issue in snapshot["issues"] if issue["number"] == 101)
            return {
                "ranking": [
                    {"number": marked["number"], "lane_id": "L3", "priority": 1, "repair": False}
                ],
                "active_lanes": [],
                "eligible_count": 1,
                "suppressed": [],
                "generated_at": None,
            }

    def loader(name, filename):
        if filename == "oc_portfolio_scheduler.py":
            return CapturingScheduler
        if filename == "oc_swarm_resource_locks.py":
            return FakeLocks
        if filename == "oc_swarm_dependency_graph.py":
            return FakeDeps
        raise AssertionError(filename)

    snapshot = _snapshot()
    snapshot["issues"][2]["body"] += "\nOC-SWARM-PROVIDER-FREE: reconcile"
    monkeypatch.setattr(swarm, "_load_sibling", loader)
    plan = swarm.build_swarm_plan(snapshot, provider_free_only=True)

    hidden = next(issue for issue in captured["issues"] if issue["number"] == 100)
    marked = next(issue for issue in captured["issues"] if issue["number"] == 101)
    dependency = next(issue for issue in captured["issues"] if issue["number"] == 99)
    assert "oc-queued" not in hidden["labels"]
    assert "oc-queued" in marked["labels"]
    assert dependency["state"] == "CLOSED"
    assert plan["selected_numbers"] == [101]
    assert plan["safety"]["provider_free_only"] is True


def _split_snapshot():
    snapshot = _snapshot()
    snapshot["issues"][1]["body"] = "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"
    return snapshot


def test_swarm_plan_routes_provider_free_work_to_its_own_matrix(monkeypatch):
    """Provider-free issues never enter the paid matrix, even with providers enabled."""
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    plan = swarm.build_swarm_plan(_split_snapshot(), worker_slots=8)
    assert plan["launch_count"] == 3
    assert plan["provider_free_launch_count"] == 1
    assert plan["provider_launch_count"] == 2
    assert [w["issue_number"] for w in plan["provider_free_matrix"]["include"]] == [100]
    assert [w["issue_number"] for w in plan["provider_matrix"]["include"]] == [101, 102]
    assert all(w["provider_free"] is True for w in plan["provider_free_workers"])
    assert all(w["provider_free"] is False for w in plan["provider_workers"])
    assert plan["safety"]["provider_free_lane_split"] is True
    # The aggregate matrix is the union, preserving the existing contract.
    assert len(plan["matrix"]["include"]) == 3
    assert {w["issue_number"] for w in plan["matrix"]["include"]} == {100, 101, 102}


def test_provider_free_only_snapshot_hides_provider_dependent_queue_entries():
    """Under NO-API mode only marked issues stay queued, so no paid worker can be planned."""
    filtered = swarm._provider_free_snapshot(_split_snapshot())
    by_number = {issue["number"]: issue for issue in filtered["issues"]}
    assert "oc-queued" in by_number[100]["labels"]
    assert "oc-queued" not in by_number[101]["labels"]
    assert "oc-queued" not in by_number[102]["labels"]
    assert swarm.is_provider_free(by_number[100]) is True
    assert swarm.is_provider_free(by_number[101]) is False


def test_github_output_carries_split_matrices(monkeypatch, tmp_path):
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    plan = swarm.build_swarm_plan(_split_snapshot(), worker_slots=8)
    output = tmp_path / "output"
    swarm._write_github_output(str(output), plan)
    text = output.read_text(encoding="utf-8")
    assert "provider_free_launch_count=1\n" in text
    assert "provider_launch_count=2\n" in text
    assert 'provider_free_matrix={"include":[{' in text
    assert 'provider_matrix={"include":[{' in text
    assert "launch_count=3\n" in text


def test_blocked_reconciliation_is_restart_stable_and_does_not_mutate_snapshot():
    snapshot = _snapshot()
    snapshot["issues"][1]["labels"] = ["oc-blocked"]
    snapshot["issues"][1]["body"] = "BLOCKED on prerequisite.\nOC-BLOCKED-ON: #99"
    original = [dict(issue, labels=list(issue["labels"])) for issue in snapshot["issues"]]

    first = swarm.blocked_reconciliation_report(snapshot)
    second = swarm.blocked_reconciliation_report(snapshot)

    assert first == second
    assert first["release_numbers"] == [100]
    assert first["results"][0]["release_authorized"] is True
    assert snapshot["issues"] == original


def test_blocked_reconciliation_holds_unknown_and_owner_gated_work():
    snapshot = {
        "issues": [
            {
                "number": 200,
                "state": "OPEN",
                "labels": ["oc-blocked"],
                "body": "",
                "comments": 1,
            },
            {
                "number": 201,
                "state": "OPEN",
                "labels": ["oc-blocked"],
                "body": "OC-BLOCKED-ON: credential",
            },
        ],
        "issue_comments": {
            "200": [{"body": "OC-BLOCKED-ON: pr#300"}],
        },
        "pull_requests": [{"number": 300, "state": "open", "merged": False}],
    }

    report = swarm.blocked_reconciliation_report(snapshot)
    by_number = {row["issue_number"]: row for row in report["results"]}
    assert by_number[200]["disposition"] == "hold"
    assert by_number[200]["release_authorized"] is False
    assert by_number[201]["disposition"] == "owner-gate"
    assert by_number[201]["release_authorized"] is False


def test_provider_free_task_is_released_from_stale_provider_budget_hold():
    fingerprint = "a" * 24
    snapshot = {
        "issues": [
            {
                "number": 1742,
                "state": "OPEN",
                "labels": ["oc-blocked", "oc-p0"],
                "body": (
                    "OC-SWARM-CAPABILITY: taxonomy-resolution\n"
                    "OC-SWARM-CAPABILITY: geospatial-context\n"
                    "OC-SWARM-CAPABILITY: locality-redaction\n"
                    "OC-SWARM-CAPABILITY: provenance-assembly\n"
                    "OC-SWARM-CAPABILITY: schema-validation\n"
                    "OC-SWARM-CAPABILITY: test-execution"
                ),
                "comments": [{"body": "OC-BLOCKED-ON: budget:" + fingerprint}],
            }
        ],
        "budget_fingerprints": {"1742": fingerprint},
    }

    report = swarm.blocked_reconciliation_report(snapshot)
    row = report["results"][0]
    assert row["issue_number"] == 1742
    assert row["disposition"] == "release"
    assert row["release_authorized"] is True
    assert report["release_numbers"] == [1742]

    # Releasing a provider budget hold does not invent an executor. Once the
    # release applier changes oc-blocked -> oc-queued, this task is deliberately
    # unstaffed and cannot fall through to the paid lane.
    queued = dict(snapshot)
    queued["issues"] = [dict(snapshot["issues"][0], labels=["oc-queued", "oc-p0"])]
    assert swarm.is_provider_free(queued["issues"][0]) is True
    assert swarm.is_lane_executable(queued["issues"][0]) is False
    assert swarm.unstaffed_numbers(queued) == [1742]


def test_blocked_budget_observations_are_scoped_by_issue_number():
    snapshot = {
        "issues": [
            {
                "number": 200,
                "state": "OPEN",
                "labels": ["oc-blocked"],
                "body": "",
                "comments": [{"body": "OC-BLOCKED-ON: budget:" + "a" * 24}],
            },
            {
                "number": 201,
                "state": "OPEN",
                "labels": ["oc-blocked"],
                "body": "",
                "comments": [{"body": "OC-BLOCKED-ON: budget:" + "a" * 24}],
            },
        ],
        "budget_fingerprints": {"200": "b" * 24, "201": "a" * 24},
    }

    report = swarm.blocked_reconciliation_report(snapshot)
    by_number = {row["issue_number"]: row for row in report["results"]}
    assert by_number[200]["disposition"] == "release"
    assert by_number[201]["disposition"] == "hold"


def test_swarm_plan_carries_blocked_report_without_relabelling(monkeypatch):
    snapshot = _snapshot()
    snapshot["issues"].append(
        {
            "number": 103,
            "title": "Parked work",
            "body": "OC-BLOCKED-ON: #99",
            "labels": ["oc-blocked"],
            "state": "OPEN",
        }
    )
    monkeypatch.setattr(swarm, "_load_sibling", _loader)

    plan = swarm.build_swarm_plan(snapshot, worker_slots=8)

    assert plan["blocked_reconciliation"]["release_numbers"] == [103]
    assert "oc-blocked" in snapshot["issues"][-1]["labels"]
    assert plan["safety"]["blocked_work_fail_closed"] is True
    assert plan["safety"]["blocked_reconciliation_mutates"] is False


def test_blocked_report_drives_enrichment_then_one_idempotent_release():
    incomplete = {
        "issues": [
            {
                "number": 200,
                "state": "OPEN",
                "labels": ["oc-blocked"],
                "body": "",
                "comments": 1,
            }
        ]
    }
    first = swarm.blocked_reconciliation_report(incomplete)
    assert first["release_plan"]["action_count"] == 0
    assert first["observation_requests"] == [{"kind": "issue_comments", "number": 200}]

    with_comment = {
        **incomplete,
        "issue_comments": {"200": [{"body": "OC-BLOCKED-ON: pr#300"}]},
    }
    second = swarm.blocked_reconciliation_report(with_comment)
    assert second["release_plan"]["action_count"] == 0
    assert second["observation_requests"] == [
        {"kind": "pull_request_state", "number": 300}
    ]

    complete = {
        **with_comment,
        "pull_requests": [{"number": 300, "state": "MERGED", "merged": True}],
    }
    third = swarm.blocked_reconciliation_report(complete)
    assert third == swarm.blocked_reconciliation_report(complete)
    assert third["observation_requests"] == []
    assert third["release_plan"]["action_count"] == 1
    action = third["release_plan"]["actions"][0]
    assert action["issue_number"] == 200
    assert action["requires_labels"] == ["oc-blocked"]
    assert action["idempotency_key"] == "blocked-release:200:pr#300"


def _edit_snapshot():
    snapshot = _snapshot()
    snapshot["issues"][1]["body"] = (
        "OC-SWARM-PROVIDER-FREE: edit\nOC-SWARM-DISPOSITION: done\nOC-SWARM-VALIDATE: ruff-check"
    )
    return snapshot


def test_edit_mode_issues_stay_queued_on_runs_off_the_integration_ref(monkeypatch):
    """A run that cannot execute the edit lane must not offer its issues for claim."""
    captured = {}

    class CapturingScheduler:
        @staticmethod
        def build_plan(snapshot):
            captured.update(snapshot)
            queued = [
                issue["number"]
                for issue in snapshot["issues"]
                if "oc-queued" in issue["labels"]
            ]
            return {
                "ranking": [
                    {"number": number, "lane_id": "L3", "priority": 0, "repair": False}
                    for number in queued
                ],
                "active_lanes": [],
                "eligible_count": len(queued),
                "suppressed": [],
                "generated_at": None,
            }

    def loader(name, filename):
        if filename == "oc_portfolio_scheduler.py":
            return CapturingScheduler
        return _loader(name, filename)

    monkeypatch.setattr(swarm, "_load_sibling", loader)
    snapshot = _edit_snapshot()
    plan = swarm.build_swarm_plan(snapshot, worker_slots=8, defer_edit_mode=True)
    deferred = next(issue for issue in captured["issues"] if issue["number"] == 100)
    assert "oc-queued" not in deferred["labels"]
    assert plan["selected_numbers"] == [101, 102]
    assert plan["edit_mode_deferred_numbers"] == [100]
    assert plan["safety"]["edit_mode_deferred"] is True
    # Deferral is a planning view: the durable snapshot is untouched.
    assert "oc-queued" in snapshot["issues"][1]["labels"]


def test_edit_mode_issues_are_planned_on_the_integration_ref(monkeypatch):
    monkeypatch.setattr(swarm, "_load_sibling", _loader)
    plan = swarm.build_swarm_plan(_edit_snapshot(), worker_slots=8)
    assert 100 in plan["selected_numbers"]
    assert plan["edit_mode_deferred_numbers"] == []
    assert plan["safety"]["edit_mode_deferred"] is False


def test_edit_mode_marker_matches_the_worker_parser():
    assert swarm.is_edit_mode({"body": "OC-SWARM-PROVIDER-FREE: EDIT\n"}) is True
    assert swarm.is_edit_mode({"body": "OC-SWARM-PROVIDER-FREE: reconcile"}) is False
    assert swarm.is_edit_mode({"body": "text OC-SWARM-PROVIDER-FREE: edit"}) is False
    assert swarm.is_edit_mode({"body": None}) is False
    # The first marker decides, exactly as the worker's MODE.search does.
    validate_first = "OC-SWARM-PROVIDER-FREE: validate\nOC-SWARM-PROVIDER-FREE: edit"
    edit_first = "OC-SWARM-PROVIDER-FREE: edit\nOC-SWARM-PROVIDER-FREE: validate"
    assert swarm.is_edit_mode({"body": validate_first}) is False
    assert swarm.is_edit_mode({"body": edit_first}) is True
    worker = importlib.util.spec_from_file_location(
        "oc_swarm_provider_free_worker", ROOT / "scripts" / "oc_swarm_provider_free_worker.py"
    )
    module = importlib.util.module_from_spec(worker)
    worker.loader.exec_module(module)
    for body in (validate_first, edit_first, "OC-SWARM-PROVIDER-FREE: EDIT"):
        planned = module.execution_plan({"number": 1, "body": body})["mode"]
        assert swarm.is_edit_mode({"body": body}) is (planned == "edit")


# ---------------------------------------------------------------------------
# Homeostasis invariant. These use the REAL scheduler, dependency graph and
# lock selector so the verdict is classified from the data the live plan has.
# ---------------------------------------------------------------------------

EXECUTABLE = "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"
UNSTAFFED = "OC-SWARM-CAPABILITY: taxonomy-resolution"


def _row(number, *labels, body=EXECUTABLE, writes=None, state="OPEN", **extra):
    resource = writes or f"module-{number}"
    return {
        "number": number,
        "title": f"P2 bounded work {number}",
        "body": f"{body}\nOC-SWARM-WRITES: {resource}",
        "labels": list(labels),
        "state": state,
        "createdAt": "2026-09-01T00:00:00Z",
        **extra,
    }


def _plan(issues, **kwargs):
    snapshot = {"issues": issues, "now": "2026-10-01T00:00:00Z"}
    snapshot.update(kwargs.pop("extra", {}))
    return swarm.build_swarm_plan(snapshot, **kwargs)


@pytest.mark.parametrize(
    "options", [{"coding_executor_available": True}, {"provider_free_only": True}],
)
@pytest.mark.parametrize(
    "capabilities", ["", UNSTAFFED, "OC-SWARM-CAPABILITY: open-ended-code-authoring"],
)
def test_unsupported_executor_never_spends_a_slot_or_routes_to_a_provider(
    options, capabilities,
):
    body = "OC-SWARM-PROVIDER-FREE: rebuild-the-graph"
    if capabilities:
        body += "\n" + capabilities
    unsupported = _row(10, "oc-queued", "oc-p0", body=body, writes="shared")
    supported = _row(11, "oc-queued", "oc-p4", writes="shared")
    plan = _plan([unsupported, supported], worker_slots=1, **options)
    assert plan["selected_numbers"] == [11]
    assert plan["launch_count"] == plan["provider_free_launch_count"] == 1
    assert plan["provider_launch_count"] == 0
    assert plan["provider_matrix"] == {"include": []}
    assert [worker["issue_number"] for worker in plan["provider_free_workers"]] == [11]
    [record] = plan["coding_dispatch"]
    assert record["issue_number"] == 10
    assert record["state"] == "capability_gap"
    assert record["gate"] == "unsupported-deterministic-executor"
    assert record["declared_executor"] == "rebuild-the-graph"
    assert record["needs_coding_executor"] is False
    assert record["dispatchable"] is False
    assert record["provider_called"] is False
    assert record["executor"] is None
    assert plan["homeostasis"]["gates"]["lane_refused"] == [10]
    assert "rebuild-the-graph" in plan["homeostasis"]["gates"]["lane_refusal_reasons"][0]["reason"]
    assert plan["homeostasis"]["healthy_idle"] is False
    assert plan["safety"]["provider_calls_in_planner"] is False


@pytest.mark.parametrize(
    "options", [{"coding_executor_available": True}, {"provider_free_only": True}],
)
def test_open_ended_code_authoring_keeps_its_provider_gate(options):
    issue = _row(10, "oc-queued", body="OC-SWARM-CAPABILITY: open-ended-code-authoring")
    plan = _plan([issue], **options)
    authorised = options.get("coding_executor_available", False)
    assert plan["provider_free_launch_count"] == 0
    assert plan["provider_launch_count"] == int(authorised)
    [record] = plan["coding_dispatch"]
    assert record["state"] == ("queued" if authorised else "provider_blocked")
    assert record["capability"] == "open-ended-code-authoring"
    assert record["dispatchable"] is authorised
    assert record["provider_called"] is False


def test_empty_queue_is_replenish_never_healthy_idle():
    plan = _plan([_row(1, "oc-done", state="CLOSED")])
    verdict = plan["homeostasis"]
    assert plan["launch_count"] == 0
    assert verdict["reason"] == "queue_empty"
    assert verdict["status"] == "replenish"
    assert verdict["healthy_idle"] is False
    assert verdict["discovery_required"] is True
    # Discovery evidence is absent, so the plan cannot claim discovery ran.
    assert verdict["evidence"]["discovery_ran"] is None


def test_healthy_idle_requires_no_unfinished_work_and_empty_discovery():
    ran_empty = {"discovery": {"ran": True, "candidate_count": 0}}
    verdict = _plan([_row(1, "oc-done", state="CLOSED")], extra=ran_empty)["homeostasis"]
    assert verdict["reason"] == "queue_empty"
    assert verdict["healthy_idle"] is True
    assert verdict["status"] == "idle"
    assert verdict["discovery_required"] is False

    # Discovery found candidates: not idle, they still have to be filed.
    found = {"discovery": {"ran": True, "candidate_count": 2}}
    verdict = _plan([], extra=found)["homeostasis"]
    assert verdict["healthy_idle"] is False and verdict["status"] == "replenish"

    # Unfinished gated work exists: an empty immediate queue is not idle.
    verdict = _plan([_row(5, "oc-owner-gate")], extra=ran_empty)["homeostasis"]
    assert verdict["healthy_idle"] is False
    assert verdict["gates"]["owner_gated"] == [5]


def test_work_blocked_only_behind_an_owner_gate_is_gated_and_recorded():
    issues = [
        _row(10, "oc-owner-gate"),
        _row(20, "oc-queued", body=EXECUTABLE + "\nOC-SWARM-DEPENDS-ON: #10"),
        # Transitively held: 30 -> 20 -> 10 (owner gate).
        _row(30, "oc-queued", body=EXECUTABLE + "\nOC-SWARM-DEPENDS-ON: #20"),
    ]
    plan = _plan(issues)
    verdict = plan["homeostasis"]
    assert plan["launch_count"] == 0
    assert verdict["reason"] == "gated_only"
    assert verdict["status"] == "gated"
    assert verdict["healthy_idle"] is False
    assert verdict["discovery_required"] is True
    assert verdict["gates"]["owner_gated"] == [10]
    blocked = {row["issue"]: row for row in verdict["gates"]["dependency_blocked"]}
    assert blocked[20]["blocked_by"] == [10] and blocked[20]["gated"] is True
    assert blocked[30]["blocked_by"] == [20] and blocked[30]["roots"] == [10]
    assert blocked[30]["gated"] is True


def test_provider_only_queue_under_no_api_mode_records_provider_parks():
    issues = [
        _row(40, "oc-queued", body="Needs a model provider."),
        _row(41, "oc-queued", body="Also needs a model provider."),
    ]
    plan = _plan(issues, provider_free_only=True)
    verdict = plan["homeostasis"]
    assert plan["launch_count"] == 0
    assert verdict["gates"]["provider_parked"] == [40, 41]
    assert verdict["reason"] == "gated_only"
    assert verdict["status"] == "gated"
    # With providers available the same work is not parked at all.
    assert _plan(issues)["homeostasis"]["gates"]["provider_parked"] == []


def test_one_blocked_module_does_not_stall_a_free_module():
    issues = [
        _row(10, "oc-owner-gate"),
        _row(20, "oc-queued", body=EXECUTABLE + "\nOC-SWARM-DEPENDS-ON: #10"),
        _row(21, "oc-queued"),
    ]
    plan = _plan(issues)
    verdict = plan["homeostasis"]
    assert plan["selected_numbers"] == [21]
    assert verdict["reason"] == "executing"
    assert verdict["status"] == "executing"
    assert [row["issue"] for row in verdict["gates"]["dependency_blocked"]] == [20]


def test_scientific_gate_is_never_admitted_and_never_stalls_others():
    issues = [
        # Highest priority and writing the same module: if it were admitted it
        # would take the slot and the lock away from #51.
        _row(50, "oc-queued", "oc-scientific-gate", "oc-p0", writes="taxonomy"),
        _row(51, "oc-queued", "oc-p3", writes="taxonomy"),
    ]
    plan = _plan(issues, worker_slots=1)
    verdict = plan["homeostasis"]
    assert plan["selected_numbers"] == [51]
    assert 50 not in plan["selected_numbers"]
    assert verdict["gates"]["scientific_gated"] == [50]
    assert verdict["reason"] == "executing"

    alone = _plan([issues[0]])
    assert alone["launch_count"] == 0
    assert alone["homeostasis"]["reason"] == "gated_only"
    assert alone["homeostasis"]["gates"]["scientific_gated"] == [50]


def test_admissible_work_left_unselected_is_an_invariant_violation(monkeypatch):
    real = swarm._load_sibling

    class SelectNothing:
        held_locks = staticmethod(lambda rows: [])

        @staticmethod
        def select_with_resource_locks(candidates, *, active_locks, capacity):
            list(candidates)
            return [], []

    def loader(name, filename):
        if filename == "oc_swarm_resource_locks.py":
            return SelectNothing
        return real(name, filename)

    monkeypatch.setattr(swarm, "_load_sibling", loader)
    plan = _plan([_row(60, "oc-queued")])
    verdict = plan["homeostasis"]
    assert plan["launch_count"] == 0
    assert verdict["reason"] == "invariant_violation"
    assert verdict["status"] == "violation"
    assert verdict["healthy_idle"] is False
    assert verdict["evidence"]["ready_unselected_lock_free"] == [60]


def test_not_planned_dependency_keeps_dependents_blocked_in_the_plan():
    issues = [
        _row(70, state="CLOSED", stateReason="NOT_PLANNED"),
        _row(71, "oc-queued", body=EXECUTABLE + "\nOC-SWARM-DEPENDS-ON: #70"),
    ]
    plan = _plan(issues)
    verdict = plan["homeostasis"]
    assert plan["launch_count"] == 0
    assert verdict["reason"] == "dependency_blocked"
    assert verdict["status"] == "waiting"
    row = verdict["gates"]["dependency_blocked"][0]
    assert row["issue"] == 71 and row["blocked_by"] == [70] and row["gated"] is False

    issues[0]["stateReason"] = "COMPLETED"
    assert _plan(issues)["selected_numbers"] == [71]


def test_saturation_lock_contention_and_lane_refusal_are_named():
    running = _row(80, "oc-running", writes="atlas")
    waiting = _row(81, "oc-queued", writes="atlas")
    assert _plan([running, waiting], worker_slots=1)["homeostasis"]["reason"] == "capacity_full"

    verdict = _plan([running, waiting], worker_slots=4)["homeostasis"]
    assert verdict["reason"] == "lock_contended"
    assert verdict["gates"]["lock_contended"] == [81]

    unstaffed = _row(82, "oc-queued", body=UNSTAFFED)
    for mode in (False, True):
        verdict = _plan([unstaffed], provider_free_only=mode)["homeostasis"]
        assert verdict["reason"] == "lane_refused", mode
        assert verdict["status"] == "capability_gap"
        assert verdict["gates"]["lane_refused"] == [82]
        assert verdict["discovery_required"] is True


def test_github_output_carries_the_homeostasis_verdict(tmp_path):
    plan = _plan([])
    output = tmp_path / "output"
    swarm._write_github_output(str(output), plan)
    text = output.read_text(encoding="utf-8")
    assert "homeostasis_status=replenish\n" in text
    assert "homeostasis_reason=queue_empty\n" in text
