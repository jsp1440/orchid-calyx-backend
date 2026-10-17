"""Durable lane telemetry: every controller wave leaves a state and a reason.

Before this, the planner's homeostasis reason reached only the run's step
summary, and 32 consecutive zero-launch waves left no durable reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts import oc_lane_status as lanes

NOW = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)
CONTROLLER = Path(".github/workflows/orchid-swarm-controller.yml")


def plan(reason="queue_empty", status="replenish", selected=()):
    return {
        "selected_numbers": list(selected),
        "homeostasis": {
            "reason": reason,
            "status": status,
            "evidence": {"queued_open": 0},
        },
    }


def record(plan_doc=None, recovery=None, *, paid=0, free=0, blocked=False):
    return lanes.build_record(
        plan_doc if plan_doc is not None else plan(),
        recovery,
        run_id="38931454921",
        run_url="https://github.com/o/r/actions/runs/38931454921",
        event="schedule",
        provider_launch_count=paid,
        provider_free_launch_count=free,
        provider_blocked=blocked,
        now=NOW,
    )


@pytest.mark.parametrize(
    ("reason", "state"),
    [
        ("queue_empty", "idle"),
        ("gated_only", "blocked"),
        ("dependency_blocked", "blocked"),
        ("lock_contended", "blocked"),
        ("lane_refused", "blocked"),
        ("held_other", "blocked"),
        ("invariant_violation", "failed"),
        ("something_new", "blocked"),
    ],
)
def test_every_zero_launch_wave_gets_a_state_and_the_planner_reason(reason, state):
    rec = record(plan(reason))
    assert rec["lane_state"] == state and rec["reason"] == reason
    assert rec["homeostasis_reason"] == reason and rec["launched"] == {
        "provider": 0,
        "provider_free": 0,
    }


def test_a_launching_wave_is_working():
    rec = record(plan("executing", "executing", [1943]), paid=1)
    assert (rec["lane_state"], rec["reason"]) == ("working", "executing")
    assert rec["selected"] == [1943]


def test_provider_free_launches_count_as_working():
    assert record(plan("executing", "executing"), free=2)["lane_state"] == "working"


def test_planned_paid_work_refused_by_the_governor_is_blocked_not_working():
    rec = record(plan("executing", "executing", [1943]), blocked=True)
    assert (rec["lane_state"], rec["reason"]) == (
        "blocked",
        "provider_blocked:executing",
    )


def test_lease_recovery_marks_the_wave_recovering():
    rec = record(
        recovery={"recovered_count": 1, "stranded_recovered_count": 0, "errors": []}
    )
    assert (rec["lane_state"], rec["reason"]) == (
        "recovering",
        "lease_recovered:queue_empty",
    )
    assert rec["leases_recovered"] == 1
    stranded = record(
        recovery={"recovered_count": 0, "stranded_recovered_count": 2, "errors": []}
    )
    assert stranded["leases_recovered"] == 2 and stranded["lane_state"] == "recovering"


def test_lease_reconcile_errors_mark_the_wave_failed():
    rec = record(recovery={"recovered_count": 0, "errors": [{"issue": 1}]})
    assert (rec["lane_state"], rec["reason"]) == (
        "failed",
        "lease_reconcile_errors:queue_empty",
    )


@pytest.mark.parametrize(
    "bad", [None, {}, {"homeostasis": None}, {"homeostasis": {"status": "x"}}]
)
def test_missing_planner_output_is_a_failure_with_a_reason(bad):
    rec = lanes.build_record(
        bad,
        None,
        run_id="1",
        run_url="u",
        event="e",
        provider_launch_count="",
        provider_free_launch_count=None,
        provider_blocked=False,
        now=NOW,
    )
    assert (rec["lane_state"], rec["reason"]) == ("failed", "plan_output_missing")


def test_render_and_parse_round_trip():
    rec = record()
    body = lanes.render(lanes.CURRENT_TAG, rec)
    assert lanes.parse(body, lanes.CURRENT_TAG) == rec
    assert lanes.parse(body, lanes.TRANSITION_TAG) is None
    assert lanes.parse("not a record", lanes.CURRENT_TAG) is None


BOT = {"login": "github-actions[bot]"}


def comment(cid, rec, *, tag=lanes.CURRENT_TAG, user=BOT):
    return {"id": cid, "user": user, "body": lanes.render(tag, rec)}


def test_first_wave_creates_current_and_a_transition():
    writes = lanes.plan_writes([], record())
    assert writes == {"current_comment_id": None, "transition": True, "previous": None}


def test_same_state_and_reason_updates_in_place_without_a_transition():
    prior = record()
    writes = lanes.plan_writes([comment(7, prior)], record())
    assert writes["current_comment_id"] == 7 and writes["transition"] is False


def test_a_change_of_state_or_reason_appends_a_transition():
    prior = record()
    writes = lanes.plan_writes([comment(7, prior)], record(plan("gated_only", "gated")))
    assert writes["transition"] is True
    assert writes["previous"] == {"lane_state": "idle", "reason": "queue_empty"}


def test_only_the_bots_own_current_comment_is_trusted():
    forged = comment(99, record(plan("gated_only")), user={"login": "drive-by"})
    writes = lanes.plan_writes([forged], record())
    assert writes["current_comment_id"] is None and writes["transition"] is True


def test_the_newest_bot_current_comment_wins():
    older = comment(5, record(plan("gated_only")))
    newer = comment(8, record())
    assert lanes.plan_writes([newer, older], record())["current_comment_id"] == 8


class FakeGitHub:
    def __init__(self, comments=()):
        self.rows = list(comments)
        self.created, self.updated = [], []

    def comments(self, issue):
        return list(self.rows)

    def create(self, issue, body):
        cid = 1000 + len(self.created)
        self.created.append(body)
        self.rows.append({"id": cid, "user": BOT, "body": body})
        return cid

    def update(self, cid, body):
        self.updated.append((cid, body))
        for row in self.rows:
            if row["id"] == cid:
                row["body"] = body


def test_publish_keeps_one_current_and_appends_only_on_change():
    gh = FakeGitHub()
    lanes.publish(gh, 1949, record())
    assert len(gh.created) == 2 and not gh.updated
    lanes.publish(gh, 1949, record())
    assert len(gh.created) == 2 and len(gh.updated) == 1
    lanes.publish(gh, 1949, record(plan("executing", "executing", [1943]), paid=1))
    assert len(gh.created) == 3 and len(gh.updated) == 2
    assert gh.created[-1].startswith("<!-- " + lanes.TRANSITION_TAG)


def test_dry_run_writes_nothing():
    gh = FakeGitHub()
    report = lanes.publish(gh, 1949, record(), dry_run=True)
    assert report["dry_run"] is True and not gh.created and not gh.updated


def test_main_never_fails_the_wave(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise OSError("gh unavailable")

    monkeypatch.setattr(lanes.subprocess, "run", broken)
    (tmp_path / "plan.json").write_text(json.dumps(plan()))
    code = lanes.main(
        [
            "--repository",
            "o/r",
            "--plan",
            str(tmp_path / "plan.json"),
            "--run-id",
            "1",
            "--run-url",
            "u",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert (
        code == 0
        and out["error"] == "OSError"
        and out["record"]["lane_state"] == "idle"
    )


def test_the_controller_publishes_lane_status_after_planning_and_never_fails_on_it():
    plan_job = yaml.safe_load(CONTROLLER.read_text())["jobs"]["plan"]
    steps = [s for s in plan_job["steps"] if s.get("name") == "Publish lane status"]
    assert len(steps) == 1
    step = steps[0]
    assert step.get("continue-on-error") is True and step.get("timeout-minutes") == 2
    assert (
        "!cancelled()" in step["if"] and "canonical_integration == 'true'" in step["if"]
    )
    assert "scripts.oc_lane_status" in step["run"]
    assert '--plan "$RUNNER_TEMP/swarm-plan.json"' in step["run"]
    assert "swarm-lease-recovery.json" in step["run"]


def test_a_selected_wave_that_launched_nothing_is_not_working():
    rec = record(plan("executing", "executing", [1943]))
    assert (rec["lane_state"], rec["reason"]) == ("blocked", "selected_not_launched")


def test_a_saturated_lane_with_running_workers_stays_working():
    assert record(plan("capacity_full", "saturated"))["lane_state"] == "working"


def test_comment_reads_stop_at_the_page_holding_current(monkeypatch):
    gh = lanes.GitHub("o/r")
    pages = {
        1: [comment(i, record(), tag=lanes.TRANSITION_TAG) for i in range(1, 100)]
        + [comment(100, record())],
        2: [comment(200 + i, record(), tag=lanes.TRANSITION_TAG) for i in range(100)],
    }
    calls = []

    def api(path, payload=None, method="GET"):
        page = int(path.rsplit("page=", 1)[1])
        calls.append(page)
        return pages.get(page, [])

    monkeypatch.setattr(gh, "_api", api)
    rows = gh.comments(1949)
    assert calls == [1] and len(rows) == 100


def test_empty_queue_with_held_unfinished_work_is_blocked_not_idle():
    doc = plan()
    doc["homeostasis"]["evidence"]["unfinished_held"] = {
        "repair_pending": 16,
        "validating": 11,
        "owner_gate": 0,
    }
    out = record(doc)
    assert (out["lane_state"], out["reason"]) == (
        "blocked",
        "queue_empty_unfinished_held",
    )
    assert out["evidence"]["unfinished_held"]["repair_pending"] == 16


def test_empty_queue_with_nothing_held_stays_idle():
    doc = plan()
    doc["homeostasis"]["evidence"]["unfinished_held"] = {"repair_pending": 0}
    assert record(doc)["lane_state"] == "idle"


# --- per-module lane state (re-observed after claiming; no claim-handoff parsing) ---


def lane(state, **kw):
    base = {
        "state": state,
        "running": [],
        "replenishable": [],
        "gates": {},
        "capability_gap": [],
        "validating": [],
        "planned": [],
    }
    base.update(kw)
    return base


def modules_plan(**lane_map):
    doc = plan()
    doc["module_lanes"] = {"schema": "oc.module-lanes.v1", "lanes": lane_map}
    return doc


def mods(plan_doc, recovery=None, observe=None):
    return lanes.build_record(
        plan_doc,
        recovery,
        run_id="1",
        run_url="u",
        event="e",
        provider_launch_count=0,
        provider_free_launch_count=0,
        provider_blocked=False,
        now=NOW,
        observe=observe,
    )["modules"]


@pytest.mark.parametrize(
    ("module_state", "expected"),
    [
        ("executing", "working"),
        ("validating", "working"),
        ("replenishable", "idle"),
        ("empty", "idle"),
        ("gated", "blocked"),
        ("capability_gap", "blocked"),
        ("novel", "unknown"),
    ],
)
def test_base_mapping_without_stronger_evidence(module_state, expected):
    got = mods(modules_plan(atlas=lane(module_state)))["atlas"]
    assert got["state"] == expected and got["module_state"] == module_state


def test_lanes_are_independent():
    got = mods(
        modules_plan(
            atlas=lane("gated", gates={"owner_gated": [5]}),
            matrix=lane("replenishable", replenishable=[6]),
        )
    )
    assert (got["atlas"]["state"], got["matrix"]["state"]) == ("blocked", "idle")


def test_planned_issue_observed_running_after_claim_is_working():
    got = mods(
        modules_plan(matrix=lane("replenishable", planned=[7])),
        observe=lambda n: ["oc-running", "oc-lane:matrix-id"],
    )["matrix"]
    assert (got["state"], got["reason"]) == ("working", "running")


def test_planned_issue_observed_not_running_keeps_base_state():
    got = mods(
        modules_plan(matrix=lane("replenishable", planned=[7])),
        observe=lambda n: ["oc-queued"],
    )["matrix"]
    assert got["state"] == "idle" and got["unresolved"] == []


def test_failed_observation_is_unknown_not_idle_or_working():
    def boom(n):
        raise OSError("api")

    got = mods(modules_plan(matrix=lane("replenishable", planned=[7])), observe=boom)
    assert got["matrix"]["state"] == "unknown"
    assert got["matrix"]["unresolved"] == [7]


def test_no_observer_means_planned_issues_are_unresolved():
    got = mods(modules_plan(matrix=lane("replenishable", planned=[7])))["matrix"]
    assert got["state"] == "unknown"


def test_unobserved_planned_issue_does_not_hide_running_evidence():
    def boom(n):
        raise OSError

    got = mods(
        modules_plan(matrix=lane("executing", running=[3], planned=[7])), observe=boom
    )["matrix"]
    assert got["state"] == "working"


def test_unobserved_plan_in_one_lane_does_not_touch_another():
    got = mods(
        modules_plan(
            matrix=lane("replenishable", planned=[7]),
            atlas=lane("gated", gates={"held": [9]}),
        )
    )
    assert (got["matrix"]["state"], got["atlas"]["state"]) == ("unknown", "blocked")


def test_observation_is_bounded():
    seen = []
    planned = list(range(1, lanes.MAX_OBSERVED + 6))
    got = mods(
        modules_plan(matrix=lane("replenishable", planned=planned)),
        observe=lambda n: seen.append(n) or [],
    )["matrix"]
    assert len(seen) == lanes.MAX_OBSERVED
    assert got["state"] == "unknown" and len(got["unresolved"]) == 5


def test_lease_evidence_outranks_running_evidence():
    rec = {"recovered": [{"issue_number": 3}], "errors": [{"issue": 4}]}
    got = mods(
        modules_plan(
            atlas=lane("executing", running=[3]),
            matrix=lane("executing", running=[4], replenishable=[4]),
        ),
        rec,
    )
    assert got["atlas"]["state"] == "recovering"
    assert got["matrix"]["state"] == "failed"  # error outranks recovery and running


@pytest.mark.parametrize("bad", [True, False, 0, -3, "7", 7.0, None])
def test_one_issue_number_rule_rejects_non_positive_ints(bad):
    assert lanes._issue_no(bad) is None
    assert lanes._issue_set([bad, {"issue": bad}], "issue") == set()
    # a malformed number can never mark a lane running, recovering or failed
    got = mods(
        modules_plan(atlas=lane("gated", gates={"held": [bad]}, running=[bad])),
        {"errors": [{"issue": bad}], "recovered": [{"issue_number": bad}]},
    )["atlas"]
    assert got["state"] == "blocked"


def test_non_string_keys_and_malformed_lanes_cannot_raise_or_poison_others():
    doc = modules_plan(
        atlas=lane("gated", gates={"held": [9]}),
        broken={"state": ["x"], "planned": "nope", "gates": 5},
    )
    doc["module_lanes"]["lanes"][12] = lane("executing")
    got = mods(doc)
    assert got["atlas"]["state"] == "blocked"
    assert 12 not in got
    assert got["broken"]["state"] in lanes.MODULE_STATES


@pytest.mark.parametrize("bad", [None, [], "x", {"lanes": []}, {"lanes": None}])
def test_missing_or_malformed_module_section_still_publishes_global_record(bad):
    doc = plan("executing", "executing", [1])
    doc["module_lanes"] = bad
    rec = lanes.build_record(
        doc,
        None,
        run_id="1",
        run_url="u",
        event="e",
        provider_launch_count=1,
        provider_free_launch_count=0,
        provider_blocked=False,
        now=NOW,
    )
    assert rec["lane_state"] == "working" and rec["modules"] == {}


def test_observer_exceptions_never_escape_and_labels_may_be_dicts_or_garbage():
    got = mods(
        modules_plan(matrix=lane("replenishable", planned=[7])),
        observe=lambda n: None,  # not iterable
    )["matrix"]
    assert got["state"] == "unknown"


def test_publish_still_works_with_modules_in_the_record():
    class Fake:
        def comments(self, issue):
            return []

        def create(self, issue, body):
            self.body = getattr(self, "body", body)
            return 1

    fake = Fake()
    rec = lanes.build_record(
        modules_plan(atlas=lane("gated")),
        None,
        run_id="1",
        run_url="u",
        event="e",
        provider_launch_count=0,
        provider_free_launch_count=0,
        provider_blocked=False,
        now=NOW,
    )
    lanes.publish(fake, 1949, rec)
    assert (
        lanes.parse(fake.body, lanes.CURRENT_TAG)["modules"]["atlas"]["state"]
        == "blocked"
    )


def test_lease_evidence_outranks_post_claim_observed_running():
    got = mods(
        modules_plan(matrix=lane("replenishable", replenishable=[4], planned=[4])),
        {"errors": [{"issue": 4}]},
        observe=lambda n: ["oc-running"],
    )["matrix"]
    assert got["state"] == "failed"


def test_parked_lease_receipts_do_not_mark_a_gated_lane_recovering():
    got = mods(
        modules_plan(atlas=lane("gated", gates={"held": [9]})),
        {"parked_lease_recovered": [{"issue_number": 9}]},
    )["atlas"]
    assert got["state"] == "blocked"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_observation_stops_when_the_shared_budget_is_spent():
    clock, seen = Clock(), []

    def slow(n):
        seen.append(n)
        clock.now += 8
        return ["oc-queued"]

    doc = modules_plan(
        matrix=lane("replenishable", planned=[1, 2, 3, 4, 5]),
        atlas=lane("replenishable", planned=[6]),
    )
    got = lanes.module_states(
        doc["module_lanes"], {}, observe=slow, budget=20, clock=clock
    )
    assert seen == [1, 2, 3]  # budget is shared across lanes, not per lane
    assert got["matrix"]["unresolved"] == [4, 5]
    assert got["atlas"]["state"] == "unknown" and got["atlas"]["unresolved"] == [6]


def test_label_reads_use_the_short_timeout(monkeypatch):
    seen = {}
    gh = lanes.GitHub("o/r")

    def fake(path, payload=None, method="GET", timeout=45):
        seen["timeout"] = timeout
        return {"labels": [{"name": "oc-running"}, "x"]}

    monkeypatch.setattr(gh, "_api", fake)
    assert gh.labels(5) == ["oc-running", "x"]
    assert seen["timeout"] == lanes.OBSERVE_CALL_TIMEOUT < 45
