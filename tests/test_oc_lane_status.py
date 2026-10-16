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
    assert step.get("continue-on-error") is True and step.get("if") == "always()"
    assert "scripts.oc_lane_status" in step["run"]
    assert '--plan "$RUNNER_TEMP/swarm-plan.json"' in step["run"]
    assert "swarm-lease-recovery.json" in step["run"]
