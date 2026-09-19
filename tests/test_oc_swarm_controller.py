from __future__ import annotations

import importlib.util
from pathlib import Path

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
