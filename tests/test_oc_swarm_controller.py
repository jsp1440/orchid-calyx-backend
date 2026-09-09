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
        count = int(snapshot["max_active_lanes"])
        selected = [
            {
                "number": 100 + i,
                "lane_id": f"L{(i % 5) + 1}",
                "priority": i % 3,
                "selection_reason": "priority",
                "repair": i == 0,
            }
            for i in range(count)
        ]
        return {
            "selected": selected,
            "active_lane_count": 2,
            "eligible_count": len(selected),
            "suppressed": [],
            "generated_at": "2026-09-09T16:00:00Z",
        }


def test_swarm_plan_is_bounded_to_hard_max(monkeypatch):
    monkeypatch.setattr(swarm, "_load_portfolio_scheduler", lambda: FakeScheduler)
    plan = swarm.build_swarm_plan({"issues": []}, worker_slots=99)
    assert plan["effective_worker_slots"] == 8
    assert plan["launch_count"] == 8
    assert len(plan["matrix"]["include"]) == 8
    assert plan["safety"]["bounded"] is True


def test_swarm_plan_preserves_worker_metadata(monkeypatch):
    monkeypatch.setattr(swarm, "_load_portfolio_scheduler", lambda: FakeScheduler)
    plan = swarm.build_swarm_plan({"issues": []}, worker_slots=3)
    assert plan["selected_numbers"] == [100, 101, 102]
    assert plan["workers"][0]["repair"] is True
    assert plan["workers"][1]["lane_id"] == "L2"
    assert plan["workers"][2]["slot"] == 3


def test_swarm_plan_strips_stabilization_freeze(monkeypatch):
    captured = {}

    class CapturingScheduler:
        @staticmethod
        def build_plan(snapshot):
            captured.update(snapshot)
            return {
                "selected": [],
                "active_lane_count": 0,
                "eligible_count": 0,
                "suppressed": [],
                "generated_at": None,
            }

    monkeypatch.setattr(swarm, "_load_portfolio_scheduler", lambda: CapturingScheduler)
    plan = swarm.build_swarm_plan({"stabilization_issue": 1193}, worker_slots=5)
    assert "stabilization_issue" not in captured
    assert captured["max_active_lanes"] == 5
    assert plan["launch_count"] == 0


def test_worker_slots_must_be_positive(monkeypatch):
    monkeypatch.setattr(swarm, "_load_portfolio_scheduler", lambda: FakeScheduler)
    try:
        swarm.build_swarm_plan({}, worker_slots=0)
    except ValueError as exc:
        assert ">= 1" in str(exc)
    else:
        raise AssertionError("expected ValueError")
