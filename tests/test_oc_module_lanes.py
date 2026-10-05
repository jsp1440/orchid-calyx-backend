from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.autonomy import module_lanes as ml

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "oc_portfolio_scheduler_lanes", ROOT / "scripts" / "oc_portfolio_scheduler.py"
)
assert _SPEC is not None and _SPEC.loader is not None
scheduler = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scheduler)

REQUIRED = {
    "Brain / Cognitive Integration", "Taxonomy", "Atlas / geography / environment", "Literature",
    "Matrix ID", "Pollinator", "Mycorrhiza", "Interaction / Knowledge Graph", "Image & Taxonomy",
    "Conservation", "Research Station", "University / Education", "Featured Genus",
    "Calyx / Education & Experience Intelligence", "Frontend / UX", "Infrastructure / federation",
}


def _issue(number, lane=None, *labels, title="work", state="OPEN", body=""):
    names = list(labels) + ([f"oc-lane:{lane}"] if lane else [])
    return {"number": number, "title": title, "labels": names, "state": state, "body": body}


def test_registry_has_every_required_module_lane_with_unique_keys():
    assert {lane.name for lane in ml.MODULE_LANES} == REQUIRED
    assert len(ml.LANES_BY_KEY) == len(ml.MODULE_LANES) == 16


def test_gate_labels_match_the_scheduler():
    assert scheduler.OWNER_GATE in ml.OWNER_GATE_LABELS
    assert scheduler.SCIENTIFIC_GATE in ml.SCIENTIFIC_GATE_LABELS


def test_lane_assignment_declared_inferred_and_fail_closed():
    assert ml.assign_lane(_issue(1, "pollinator")) == ("pollinator", "declared")
    marked = _issue(2, body="OC-MODULE-LANE: Featured-Genus")
    assert ml.assign_lane(marked) == ("featured-genus", "declared")
    assert ml.assign_lane(_issue(3, title="Literature DOI normalisation")) == ("literature", "inferred")
    # Two lanes named in one title: ambiguous, so not guessed.
    assert ml.assign_lane(_issue(4, title="Atlas and literature handoff")) == (ml.UNASSIGNED, "none")
    # A declaration that names no lane is wrong, not absent: never re-inferred.
    assert ml.assign_lane(_issue(5, "no-such-lane", title="Literature work")) == (ml.UNASSIGNED, "none")
    # Conflicting declarations fail closed.
    both = _issue(6, "taxonomy", body="OC-MODULE-LANE: atlas-geography-environment")
    assert ml.assign_lane(both) == (ml.UNASSIGNED, "none")
    assert ml.assign_lane(_issue(7, title="something unrelated")) == (ml.UNASSIGNED, "none")


def _states(report):
    return {k: v["state"] for k, v in report["lanes"].items()}


def test_lane_states_are_computed_from_each_lanes_own_issues_only():
    report = ml.lane_report(
        [
            _issue(10, "literature", "oc-queued"),
            _issue(11, "atlas-geography-environment", "oc-queued", "oc-owner-gate"),
            _issue(12, "taxonomy", "oc-running"),
            _issue(13, "pollinator", "oc-queued", "oc-scientific-gate"),
            _issue(14, "frontend-ux", "oc-queued"),
            _issue(15, "mycorrhiza", "oc-done", state="CLOSED"),
        ],
        provider_gated=[14],
    )
    states = _states(report)
    assert states["literature"] == "replenishable"
    assert report["lanes"]["literature"]["next_mission"] == 10
    assert states["atlas-geography-environment"] == "gated"
    assert report["lanes"]["atlas-geography-environment"]["gates"] == {"owner_gated": [11]}
    assert states["taxonomy"] == "executing"
    assert report["lanes"]["pollinator"]["gates"] == {"scientific_gated": [13]}
    assert states["frontend-ux"] == "gated"
    assert report["lanes"]["frontend-ux"]["gates"] == {"provider_blocked": [14]}
    assert states["mycorrhiza"] == "empty"  # nothing unfinished: discovery should replenish
    assert report["summary"]["replenishable"] == ["literature"]
    # Every registered lane is reported, including ones with no work.
    assert set(report["lanes"]) == set(ml.LANES_BY_KEY) | {ml.UNASSIGNED}


def test_a_blocked_lane_never_changes_another_lanes_state():
    base = [_issue(20, "literature", "oc-queued"), _issue(21, "calyx-education-intelligence", "oc-queued")]
    healthy = ml.lane_report(base)
    for blocker in ("oc-owner-gate", "oc-scientific-gate"):
        blocked = ml.lane_report([base[0], _issue(21, "calyx-education-intelligence", "oc-queued", blocker)])
        assert blocked["lanes"]["literature"] == healthy["lanes"]["literature"]
        assert blocked["lanes"]["calyx-education-intelligence"]["state"] == "gated"
    # And the reverse: Calyx needing a coding executor nobody may run.
    gap = ml.lane_report(base, provider_gated=[21])
    assert gap["lanes"]["literature"] == healthy["lanes"]["literature"]
    assert gap["lanes"]["calyx-education-intelligence"]["gates"] == {"provider_blocked": [21]}


def test_human_gates_outrank_provider_and_dependency_gates():
    report = ml.lane_report(
        [_issue(30, "taxonomy", "oc-queued", "oc-owner-gate"),
         _issue(31, "taxonomy", "oc-queued", "oc-scientific-gate")],
        provider_gated=[30, 31], dependency_blocked=[30, 31],
    )
    assert report["lanes"]["taxonomy"]["gates"] == {"owner_gated": [30], "scientific_gated": [31]}


def test_unstaffed_work_is_a_capability_gap_not_idle_and_not_executing():
    report = ml.lane_report([_issue(40, "featured-genus", "oc-queued")], capability_gap=[40])
    lane = report["lanes"]["featured-genus"]
    assert lane["state"] == "capability_gap" and lane["capability_gap"] == [40]
    assert lane["next_mission"] is None


def test_replenishment_picks_the_lowest_numbered_ungated_queued_mission():
    report = ml.lane_report(
        [_issue(52, "literature", "oc-queued"), _issue(50, "literature", "oc-queued", "oc-owner-gate"),
         _issue(51, "literature", "oc-queued")]
    )
    assert report["lanes"]["literature"]["next_mission"] == 51


def test_unassigned_work_is_counted_not_hidden():
    report = ml.lane_report([_issue(60, None, "oc-queued", title="something unrelated")])
    assert report["unassigned_unfinished"] == 1
    assert all(lane["state"] == "empty" for key, lane in report["lanes"].items() if key != ml.UNASSIGNED)


@pytest.mark.parametrize("held", ["oc-blocked", "oc-runtime-backoff", "oc-repair-backoff"])
def test_held_labels_gate_the_issue(held):
    report = ml.lane_report([_issue(70, "conservation", "oc-queued", held)])
    assert report["lanes"]["conservation"]["gates"] == {"held": [70]}


# ---- controller integration ---------------------------------------------------


def _controller():
    spec = importlib.util.spec_from_file_location(
        "oc_swarm_controller_lanes", ROOT / "scripts" / "oc_swarm_controller.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXEC = "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-WRITES: {w}"
UNSTAFFED = "OC-SWARM-CAPABILITY: taxonomy-resolution\nOC-SWARM-WRITES: {w}"


def test_plan_reports_module_lanes_and_a_gated_lane_does_not_freeze_the_others():
    swarm = _controller()
    snapshot = {
        "now": "2026-10-01T00:00:00Z",
        "issues": [
            _issue(1, "literature", "oc-queued", body=EXEC.format(w="lit")),
            _issue(2, "atlas-geography-environment", "oc-queued", "oc-owner-gate", body=EXEC.format(w="atlas")),
            _issue(3, "calyx-education-intelligence", "oc-queued", body=UNSTAFFED.format(w="calyx")),
        ],
    }
    plan = swarm.build_swarm_plan(snapshot)
    lanes = plan["module_lanes"]["lanes"]
    assert plan["selected_numbers"] == [1]
    assert lanes["literature"]["state"] == "replenishable"
    assert lanes["atlas-geography-environment"]["gates"] == {"owner_gated": [2]}
    assert lanes["calyx-education-intelligence"]["state"] == "capability_gap"
    assert plan["module_lanes"]["schema"] == "oc.module-lanes.v1"
    # The registry never changes slot selection.
    assert plan["launch_count"] == 1
