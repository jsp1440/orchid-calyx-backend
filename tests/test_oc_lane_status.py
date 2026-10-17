"""Durable lane telemetry: every controller wave leaves a state and a reason.

Before this, the planner's homeostasis reason reached only the run's step
summary, and 32 consecutive zero-launch waves left no durable reason.
"""

from __future__ import annotations

import itertools
import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts import oc_lane_status as lanes
from scripts.oc_swarm_claim import claim_workers
from tests.test_oc_swarm_claim import GitHub as ClaimGitHub
from tests.test_oc_swarm_claim import issue as claim_issue

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


# --- per-module-lane telemetry (module_lanes -> Mission Control states) -------


def lane(state="empty", *, running=(), gates=None, refusals=(), gap=(), validating=(),
         replenishable=(), unfinished=0):
    return {
        "state": state,
        "running": list(running),
        "next_mission": min(replenishable) if replenishable else None,
        "replenishable": list(replenishable),
        "gates": gates or {},
        "capability_gap": list(gap),
        "validating": list(validating),
        "refusal_reasons": list(refusals),
        "unfinished": unfinished,
    }


def with_lanes(lanes_map, base=None):
    doc = base or plan()
    doc["module_lanes"] = {
        "schema": "oc.module-lanes.v1",
        "lanes": {"unassigned": lane(), **lanes_map},
    }
    return doc


def lane_entry(doc, key, recovery=None):
    return record(doc, recovery)["module_lanes"]["lanes"][key]


@pytest.mark.parametrize(
    ("module_state", "kwargs", "state"),
    [
        ("executing", {"running": [11]}, "working"),
        ("validating", {"validating": [12]}, "working"),
        ("replenishable", {"replenishable": [13]}, "idle"),
        ("empty", {}, "idle"),
        ("gated", {"gates": {"owner_gated": [14]}}, "blocked"),
        ("capability_gap", {"gap": [15]}, "blocked"),
    ],
)
def test_module_state_maps_to_the_five_mission_control_states(module_state, kwargs, state):
    entry = lane_entry(with_lanes({"taxonomy": lane(module_state, **kwargs)}), "taxonomy")
    assert entry["lane_state"] == state and entry["module_state"] == module_state
    assert entry["lane_state"] in lanes.LANE_STATES


def test_the_mapping_is_documented_and_covers_every_engine_state():
    from app.autonomy.module_lanes import lane_report

    states = set(lane_report([])["summary"])
    assert states == set(lanes.MODULE_STATE_MAP)
    assert set(lanes.MODULE_STATE_MAP.values()) <= set(lanes.LANE_STATES)
    assert lanes.MODULE_STATE_MAP["validating"] == "working"
    assert "failed" not in lanes.MODULE_STATE_MAP.values()
    assert "recovering" not in lanes.MODULE_STATE_MAP.values()


def test_every_lane_carries_a_reason_never_blank():
    doc = with_lanes(
        {
            "taxonomy": lane("executing", running=[1]),
            "literature": lane("empty"),
            "atlas-geography-environment": lane("gated", gates={"owner_gated": [2]}),
            "matrix-id": lane("gated"),  # gated but the engine recorded no gate
            "pollinator": lane("capability_gap", gap=[3]),
        }
    )
    out = record(doc)["module_lanes"]["lanes"]
    assert all(isinstance(e["reason"], str) and e["reason"].strip() for e in out.values())
    assert out["atlas-geography-environment"]["reason"] == "owner_gated"
    assert out["matrix-id"]["reason"] == "no_reason_recorded"
    assert out["pollinator"]["reason"] == "no_reason_recorded"
    assert out["taxonomy"]["reason"] == "module_state:executing"


def test_engine_refusal_reasons_are_reused_as_the_lane_reason():
    doc = with_lanes(
        {
            "pollinator": lane(
                "capability_gap",
                gap=[3],
                refusals=[{"issue": 3, "reason": "no_authorised_coding_executor"}],
            ),
            "atlas-geography-environment": lane(
                "gated",
                gates={"provider_blocked": [4], "owner_gated": [5]},
                refusals=[{"issue": 4, "reason": "provider_blocked_by_no_api"}],
            ),
        }
    )
    out = record(doc)["module_lanes"]["lanes"]
    assert out["pollinator"]["reason"] == "no_authorised_coding_executor"
    assert out["atlas-geography-environment"]["reason"] == (
        "owner_gated,provider_blocked,provider_blocked_by_no_api"
    )


def test_unassigned_is_not_reported_as_a_module_lane_and_global_fields_are_unchanged():
    doc = with_lanes({"taxonomy": lane("executing", running=[1])})
    rec = record(doc)
    assert "unassigned" not in rec["module_lanes"]["lanes"]
    plain = record(plan())
    for key in ("lane_state", "reason", "launched", "selected", "evidence", "schema"):
        assert rec[key] == plain[key]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "executing",
        [],
        {},
        {"state": "exploding"},
        {"state": None},
        {"state": ["executing"]},
        {"state": "executing", "running": "not-a-list"},
    ],
)
def test_malformed_lane_data_fails_closed_to_unknown_not_idle(bad):
    entry = lane_entry(with_lanes({"taxonomy": bad}), "taxonomy")
    assert entry["lane_state"] == "unknown"
    assert entry["reason"] and entry["reason"] != "no_reason_recorded"


@pytest.mark.parametrize(
    ("block", "status"),
    [
        (None, "unavailable"),
        ("garbage", "malformed"),
        ({"schema": "other", "lanes": {}}, "malformed"),
        ({"schema": "oc.module-lanes.v1", "lanes": []}, "malformed"),
    ],
)
def test_missing_or_malformed_module_lanes_block_is_visible_not_silent(block, status):
    doc = plan()
    if block is not None:
        doc["module_lanes"] = block
    section = record(doc)["module_lanes"]
    assert section["status"] == status and section["lanes"] == {} and section["reason"]


def test_failed_and_recovering_come_only_from_lease_evidence_for_that_lane():
    doc = with_lanes(
        {
            "taxonomy": lane("executing", running=[10]),
            "literature": lane("executing", running=[20]),
            "matrix-id": lane("replenishable", replenishable=[30]),
        }
    )
    recovery = {
        "recovered_count": 1,
        "recovered": [{"issue_number": 10}],
        "stranded_recovered": [],
        "parked_lease_recovered": [],
        "errors": [{"issue": 30, "reason": "lease_reconcile_unconfirmed"}],
    }
    out = record(doc, recovery)["module_lanes"]["lanes"]
    assert (out["taxonomy"]["lane_state"], out["taxonomy"]["reason"]) == (
        "recovering",
        "lease_recovered:module_state:executing",
    )
    assert (out["matrix-id"]["lane_state"], out["matrix-id"]["reason"]) == (
        "failed",
        "lease_reconcile_errors:module_state:replenishable",
    )
    assert out["literature"]["lane_state"] == "working"  # no evidence about 20


def test_no_lane_is_failed_or_recovering_without_evidence():
    doc = with_lanes({k: lane("empty") for k in ("taxonomy", "literature")})
    for recovery in (None, {}, {"recovered_count": 0, "errors": []}):
        states = {e["lane_state"] for e in record(doc, recovery)["module_lanes"]["lanes"].values()}
        assert states == {"idle"}


def test_global_recovery_count_alone_does_not_invent_a_lane_recovery():
    # The global flag says something recovered, but names no issue: no lane is blamed.
    doc = with_lanes({"taxonomy": lane("executing", running=[10])})
    recovery = {"recovered_count": 2, "recovered": [], "errors": [{"reason": "x"}]}
    assert record(doc, recovery)["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "working"


def test_summary_counts_cover_every_lane_including_unknown():
    doc = with_lanes({"taxonomy": lane("executing", running=[1]), "literature": "bad"})
    counts = record(doc)["module_lanes"]["counts"]
    assert counts == {"working": 1, "unknown": 1}


def test_record_with_module_lanes_round_trips_and_is_json_serialisable():
    rec = record(with_lanes({"taxonomy": lane("executing", running=[1])}))
    assert lanes.parse(lanes.render(lanes.CURRENT_TAG, rec), lanes.CURRENT_TAG) == rec


def _wave(lane_map):
    return record(with_lanes(lane_map))


def test_a_single_lane_change_appends_a_transition_naming_the_lane():
    gh = FakeGitHub()
    lanes.publish(gh, 1949, _wave({"taxonomy": lane("empty")}))
    assert len(gh.created) == 2
    lanes.publish(gh, 1949, _wave({"taxonomy": lane("empty")}))
    assert len(gh.created) == 2  # identical wave: no spam
    result = lanes.publish(gh, 1949, _wave({"taxonomy": lane("executing", running=[1])}))
    assert len(gh.created) == 3
    assert result["lane_changes"] == [
        {
            "lane": "taxonomy",
            "from": {"lane_state": "idle", "reason": "module_state:empty"},
            "to": {"lane_state": "working", "reason": "module_state:executing"},
        }
    ]
    body = gh.created[-1]
    assert body.startswith("<!-- " + lanes.TRANSITION_TAG) and "module_lane_changes" in body
    assert "module_lane_changes" not in gh.rows[0]["body"]


def test_changes_inside_a_lane_that_keep_state_and_reason_do_not_spam():
    gh = FakeGitHub()
    lanes.publish(gh, 1949, _wave({"taxonomy": lane("executing", running=[1])}))
    lanes.publish(gh, 1949, _wave({"taxonomy": lane("executing", running=[1, 2], unfinished=5)}))
    assert len(gh.created) == 2


def test_a_legacy_previous_record_without_lanes_does_not_trigger_a_transition():
    legacy = record(plan())
    legacy.pop("module_lanes")
    writes = lanes.plan_writes([comment(7, legacy)], _wave({"taxonomy": lane("empty")}))
    assert writes["transition"] is False and "lane_changes" not in writes


def test_a_lane_appearing_or_disappearing_is_a_change():
    prior = _wave({"taxonomy": lane("empty")})
    writes = lanes.plan_writes(
        [comment(7, prior)], _wave({"taxonomy": lane("empty"), "literature": lane("empty")})
    )
    assert writes["transition"] is True
    assert writes["lane_changes"][0]["lane"] == "literature"
    assert writes["lane_changes"][0]["from"] is None


def test_first_wave_with_lanes_keeps_the_original_plan_writes_shape():
    writes = lanes.plan_writes([], _wave({"taxonomy": lane("empty")}))
    assert writes == {"current_comment_id": None, "transition": True, "previous": None}


def test_a_real_module_lane_report_flows_through_end_to_end():
    from app.autonomy.module_lanes import lane_report

    report = lane_report(
        [
            {"number": 1, "title": "Taxonomy sweep", "labels": ["oc-running"], "state": "OPEN"},
            {"number": 2, "title": "Literature DOI check", "labels": ["oc-validating"], "state": "OPEN"},
            {"number": 3, "title": "Matrix key", "labels": ["oc-queued", "oc-owner-gate"], "state": "OPEN"},
        ]
    )
    doc = plan()
    doc["module_lanes"] = report
    out = record(doc)["module_lanes"]
    assert out["status"] == "ok"
    assert out["lanes"]["taxonomy"]["lane_state"] == "working"
    assert out["lanes"]["literature"]["lane_state"] == "working"
    assert out["lanes"]["matrix-id"]["lane_state"] == "blocked"
    assert out["lanes"]["matrix-id"]["reason"] == "owner_gated"
    assert out["lanes"]["pollinator"]["lane_state"] == "idle"
    assert len(out["lanes"]) == 16


# --- claim evidence: the plan is written BEFORE the claim step ----------------


def claims_doc(confirmed=(), errors=(), skipped=()):
    return {
        "schema": "oc.swarm-claim-handoff.v1",
        "run_id": 1,
        "launch_count": len(confirmed),
        "planned_count": len(confirmed) + len(skipped) + len(errors),
        "skipped": [{"issue": n, "reason": reason} for n, reason in skipped],
        "confirmed": [
            {"issue_number": n, "reads": [], "writes": ["control-plane"], "dependencies": [],
             "provider_free": free, "lane_executable": free, "acquisition": False,
             "lease_comment_id": 900 + n, "material_fingerprint": f"fp{n}"}
            for n, free in confirmed
        ],
        "errors": [
            {"issue": n, "phase": "claim", "reason": "claim_unconfirmed"} for n in errors
        ],
    }


def claimed_record(lane_map, claims, recovery=None):
    return lanes.build_record(
        with_lanes(lane_map),
        recovery,
        run_id="1",
        run_url="u",
        event="schedule",
        provider_launch_count=0,
        provider_free_launch_count=0,
        provider_blocked=False,
        claims=lanes.claim_evidence(claims),
        now=NOW,
    )


def planned_lane(*planned, state="replenishable"):
    return lane(state, replenishable=list(planned)) | {"planned": list(planned)}


def test_confirmed_claim_makes_a_planned_lane_working_with_the_evidence_as_reason():
    rec = claimed_record({"taxonomy": planned_lane(7), "literature": planned_lane(8)},
                         claims_doc(confirmed=[(7, False), (8, True)]))
    out = rec["module_lanes"]["lanes"]
    assert (out["taxonomy"]["lane_state"], out["taxonomy"]["reason"]) == (
        "working", "claim_confirmed:provider")
    assert (out["literature"]["lane_state"], out["literature"]["reason"]) == (
        "working", "claim_confirmed:provider_free")
    assert rec["module_lanes"]["claims"]["status"] == "ok"


def test_planned_without_a_confirmed_claim_is_idle_planned_unconfirmed():
    out = claimed_record({"taxonomy": planned_lane(7)}, claims_doc())["module_lanes"]["lanes"]
    assert (out["taxonomy"]["lane_state"], out["taxonomy"]["reason"]) == (
        "idle", "planned_unconfirmed")


def test_a_lane_with_nothing_planned_keeps_its_ordinary_reason_when_claims_exist():
    out = claimed_record({"taxonomy": lane("empty")}, claims_doc())["module_lanes"]["lanes"]
    assert out["taxonomy"]["reason"] == "module_state:empty"


def test_a_claim_error_naming_a_lane_issue_is_surfaced_without_inventing_failure():
    out = claimed_record({"taxonomy": planned_lane(7)}, claims_doc(errors=[7]))["module_lanes"]["lanes"]
    assert out["taxonomy"]["lane_state"] == "idle"
    assert out["taxonomy"]["reason"] == "claim_error:planned_unconfirmed"


def test_a_claim_error_on_another_lanes_issue_does_not_touch_this_lane():
    out = claimed_record({"taxonomy": planned_lane(7), "literature": planned_lane(8)},
                         claims_doc(errors=[8]))["module_lanes"]["lanes"]
    assert out["taxonomy"]["reason"] == "planned_unconfirmed"
    assert out["literature"]["reason"].startswith("claim_error:")


def test_confirmed_claim_plus_error_in_one_lane_is_working_and_shows_the_error():
    out = claimed_record({"taxonomy": planned_lane(7, 9)},
                         claims_doc(confirmed=[(7, False)], errors=[9]))["module_lanes"]["lanes"]
    assert out["taxonomy"] == {**out["taxonomy"], "lane_state": "working",
                               "reason": "claim_error:claim_confirmed:provider"}


def test_claim_evidence_still_yields_to_lease_evidence_on_the_same_lane():
    rec = claimed_record({"taxonomy": planned_lane(7)}, claims_doc(confirmed=[(7, False)]),
                         recovery={"recovered": [{"issue_number": 7}]})
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert (entry["lane_state"], entry["reason"]) == (
        "recovering", "lease_recovered:claim_confirmed:provider")


def test_missing_claims_make_planned_lanes_unknown_and_leave_unplanned_lanes_alone():
    # Reverses the earlier "missing file keeps the old mapping": a step that fails
    # before the claim step leaves no handoff, and the pre-claim plan is then stale.
    doc = with_lanes({"taxonomy": planned_lane(7), "literature": lane("empty")})
    rec = record(doc)
    assert rec["module_lanes"]["claims"] == {"status": "unavailable", "reason": "claims_missing"}
    planned = rec["module_lanes"]["lanes"]["taxonomy"]
    assert (planned["lane_state"], planned["reason"]) == ("unknown", "claims_unavailable")
    unplanned = rec["module_lanes"]["lanes"]["literature"]
    assert (unplanned["lane_state"], unplanned["reason"]) == ("idle", "module_state:empty")


def test_default_claims_input_absent_planned_lane_is_unknown_through_main(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    (tmp_path / "plan.json").write_text(json.dumps(with_lanes({"taxonomy": planned_lane(7)})))
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    lanes.main(["--repository", "o/r", "--plan", str(tmp_path / "plan.json"),
                "--run-id", "1", "--run-url", "u"])
    out = json.loads(capsys.readouterr().out)
    assert out["record"]["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "unknown"


@pytest.mark.parametrize(
    "bad",
    [
        "text",
        [],
        {"schema": "other", "confirmed": [], "errors": []},
        {"schema": "oc.swarm-claim-handoff.v1", "confirmed": "x", "errors": []},
        {"schema": "oc.swarm-claim-handoff.v1", "confirmed": [{"issue_number": "?"}], "errors": []},
        {"schema": "oc.swarm-claim-handoff.v1", "confirmed": [], "errors": [3]},
    ],
)
def test_malformed_claims_fail_closed_for_planned_lanes(bad):
    rec = claimed_record({"taxonomy": planned_lane(7), "literature": lane("empty")}, bad)
    out = rec["module_lanes"]["lanes"]
    assert rec["module_lanes"]["claims"]["status"] == "malformed"
    assert (out["taxonomy"]["lane_state"], out["taxonomy"]["reason"]) == (
        "unknown", "claims_malformed")
    assert out["literature"]["lane_state"] == "idle"


def test_load_claim_evidence_missing_unreadable_and_ok(tmp_path):
    assert lanes.load_claim_evidence(None)["status"] == "unavailable"
    assert lanes.load_claim_evidence(str(tmp_path / "nope.json"))["status"] == "unavailable"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert lanes.load_claim_evidence(str(bad))["status"] == "malformed"
    good = tmp_path / "good.json"
    good.write_text(json.dumps(claims_doc(confirmed=[(7, False)])))
    assert lanes.load_claim_evidence(str(good))["status"] == "ok"


def test_default_claims_path_comes_from_runner_temp_only_if_the_file_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    assert lanes.default_claims_path() is None
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    assert lanes.default_claims_path() is None
    (tmp_path / "swarm-claims.json").write_text("{}")
    assert lanes.default_claims_path() == str(tmp_path / "swarm-claims.json")


def test_main_reads_claims_and_a_claim_confirmed_lane_appends_a_transition(tmp_path):
    gh = FakeGitHub()
    lanes.publish(gh, 1949, claimed_record({"taxonomy": planned_lane(7)}, claims_doc()))
    assert len(gh.created) == 2
    result = lanes.publish(
        gh, 1949,
        claimed_record({"taxonomy": planned_lane(7)}, claims_doc(confirmed=[(7, False)])),
    )
    assert len(gh.created) == 3
    assert result["lane_changes"][0]["from"]["reason"] == "planned_unconfirmed"
    assert result["lane_changes"][0]["to"] == {
        "lane_state": "working", "reason": "claim_confirmed:provider"}


def test_main_cli_accepts_claims_flag(tmp_path, monkeypatch, capsys):
    (tmp_path / "plan.json").write_text(json.dumps(with_lanes({"taxonomy": planned_lane(7)})))
    (tmp_path / "claims.json").write_text(json.dumps(claims_doc(confirmed=[(7, False)])))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "empty"))
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    lanes.main(["--repository", "o/r", "--plan", str(tmp_path / "plan.json"),
                "--claims", str(tmp_path / "claims.json"), "--run-id", "1", "--run-url", "u"])
    out = json.loads(capsys.readouterr().out)
    assert out["record"]["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "working"


# --- malformed element types and exception safety ------------------------------


def _bad_lane(**override):
    base = lane("gated", gates={"owner_gated": [7]})
    base.update(override)
    return base


@pytest.mark.parametrize(
    "bad",
    [
        _bad_lane(gates={1: [7]}),
        _bad_lane(gates={None: [7]}),
        _bad_lane(gates={(1, 2): [7]}),
        _bad_lane(gates={"": [7]}),
        _bad_lane(gates={"owner_gated": 7}),
        _bad_lane(gates={"owner_gated": ["7"]}),
        _bad_lane(running=["x"]),
        _bad_lane(running=[None]),
        _bad_lane(running=[True]),
        _bad_lane(validating=[1.5]),
        _bad_lane(replenishable=[{}]),
        _bad_lane(capability_gap=["gap"]),
        _bad_lane(planned=["p"]),
        _bad_lane(refusal_reasons=["not-a-row"]),
        _bad_lane(refusal_reasons=[{"issue": 1, "reason": 5}]),
        _bad_lane(refusal_reasons=[{"issue": 1}]),
    ],
)
def test_malformed_element_types_fail_closed_to_unknown_without_raising(bad):
    entry = lane_entry(with_lanes({"taxonomy": bad}), "taxonomy")
    assert entry["lane_state"] == "unknown" and entry["reason"] == "malformed_lane_entry"


def test_one_bad_lane_does_not_affect_a_good_lane_or_the_global_record(monkeypatch):
    doc = with_lanes(
        {
            "taxonomy": _bad_lane(gates={1: [7]}),
            "literature": lane("executing", running=[2]),
        }
    )
    rec = record(doc)
    assert rec["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "unknown"
    assert rec["module_lanes"]["lanes"]["literature"]["lane_state"] == "working"
    assert (rec["lane_state"], rec["reason"]) == ("idle", "queue_empty")
    gh = FakeGitHub()
    lanes.publish(gh, 1949, rec)
    assert len(gh.created) == 2


def test_an_unexpected_exception_in_one_lane_derivation_is_that_lane_unknown(monkeypatch):
    real = lanes._module_reason

    def boom(module_state, entry):
        if entry["running"] == [666]:
            raise RuntimeError("boom")
        return real(module_state, entry)

    monkeypatch.setattr(lanes, "_module_reason", boom)
    out = record(
        with_lanes(
            {
                "taxonomy": lane("executing", running=[666]),
                "literature": lane("executing", running=[2]),
            }
        )
    )["module_lanes"]["lanes"]
    assert (out["taxonomy"]["lane_state"], out["taxonomy"]["reason"]) == (
        "unknown",
        "lane_derivation_error",
    )
    assert out["literature"]["lane_state"] == "working"


def test_a_failure_in_the_module_lane_section_never_blocks_the_global_record(monkeypatch):
    def boom(*args, **kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(lanes, "module_lane_states", boom)
    rec = record(with_lanes({"taxonomy": lane("executing", running=[1])}))
    assert (rec["lane_state"], rec["reason"]) == ("idle", "queue_empty")
    section = rec["module_lanes"]
    assert section["status"] == "error" and section["reason"] == "module_lane_states_error"
    assert section["lanes"] == {}
    gh = FakeGitHub()
    lanes.publish(gh, 1949, rec)
    assert len(gh.created) == 2


def test_non_string_lane_keys_do_not_raise():
    doc = with_lanes({"taxonomy": lane("empty")})
    doc["module_lanes"]["lanes"][5] = lane("empty")
    out = record(doc)["module_lanes"]["lanes"]
    assert out["5"]["lane_state"] == "idle" and out["taxonomy"]["lane_state"] == "idle"


# --- one strict issue-number rule: no bools, floats, strings, zero or negatives ---

BAD_NUMBERS = [True, False, 1.0, "1", 0, -1, None]


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_issue_no_accepts_only_positive_real_ints(bad):
    assert lanes._issue_no(bad) is None
    assert lanes._issue_no(7) == 7


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_bad_issue_number_in_a_confirmed_claim_is_malformed_never_working(bad):
    doc = claims_doc()
    doc["confirmed"] = [{"issue_number": bad, "lane_executable": False}]
    rec = claimed_record({"taxonomy": planned_lane(1)}, doc)
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert rec["module_lanes"]["claims"]["status"] == "malformed"
    assert entry["lane_state"] == "unknown" and entry["reason"] == "claims_malformed"


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_bad_issue_number_in_a_claim_error_row_is_malformed(bad):
    doc = claims_doc()
    doc["errors"] = [{"issue": bad, "reason": "claim_unconfirmed"}]
    rec = claimed_record({"taxonomy": planned_lane(1)}, doc)
    assert rec["module_lanes"]["claims"]["status"] == "malformed"
    assert rec["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "unknown"


@pytest.mark.parametrize("bad", [b for b in BAD_NUMBERS if b is not None])
@pytest.mark.parametrize(
    "field", ["recovered", "stranded_recovered", "parked_lease_recovered"]
)
def test_bad_issue_number_in_recovery_lists_never_marks_a_lane_recovering(field, bad):
    doc = with_lanes({"taxonomy": lane("executing", running=[1])})
    out = record(doc, {field: [{"issue_number": bad}]})["module_lanes"]["lanes"]["taxonomy"]
    assert out["lane_state"] == "working"


@pytest.mark.parametrize("bad", [b for b in BAD_NUMBERS if b is not None])
def test_bad_issue_number_in_recovery_errors_never_marks_a_lane_failed(bad):
    doc = with_lanes({"taxonomy": lane("executing", running=[1])})
    out = record(doc, {"errors": [{"issue": bad}]})["module_lanes"]["lanes"]["taxonomy"]
    assert out["lane_state"] == "working"


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", 0, -1])
def test_bad_issue_number_inside_lane_lists_is_a_malformed_lane(bad):
    entry = lane_entry(with_lanes({"taxonomy": lane("executing", running=[bad])}), "taxonomy")
    assert (entry["lane_state"], entry["reason"]) == ("unknown", "malformed_lane_entry")


def test_selected_and_counts_reject_bools_and_non_integral_values():
    doc = plan("executing", "executing", [1943, True, 1.5, "7", -3, 0])
    rec = record(doc, {"recovered_count": True, "errors": True}, paid=True, free=1.5)
    assert rec["selected"] == [1943]
    assert rec["launched"] == {"provider": 0, "provider_free": 0}
    assert rec["leases_recovered"] == 0 and rec["lease_reconcile_errors"] == 0


def test_cli_style_digit_strings_still_count():
    rec = record(plan("executing", "executing", [1]), paid="2", free=" 1 ")
    assert rec["launched"] == {"provider": 2, "provider_free": 1}


# --- skipped rows: the plan no longer describes that issue ---------------------

SKIP = (7, "not_exclusively_queued")


def test_a_planned_issue_the_claim_step_skipped_is_unknown_with_the_engine_reason():
    rec = claimed_record({"taxonomy": planned_lane(7)}, claims_doc(skipped=[SKIP]))
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert (entry["lane_state"], entry["reason"]) == (
        "unknown", "claim_skipped:not_exclusively_queued")
    assert entry["skipped_issues"] == [7]


def test_skipped_and_confirmed_on_different_issues_keeps_working_and_shows_the_skip():
    rec = claimed_record({"taxonomy": planned_lane(7, 8)},
                         claims_doc(confirmed=[(8, False)], skipped=[SKIP]))
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert entry["lane_state"] == "working"
    assert entry["reason"] == "claim_confirmed:provider;claim_skipped:not_exclusively_queued"
    assert entry["skipped_issues"] == [7]


def test_several_skip_reasons_are_all_named_sorted_and_unique():
    rec = claimed_record(
        {"taxonomy": planned_lane(7, 8, 9)},
        claims_doc(skipped=[(7, "issue_changed_since_plan"), (8, "not_exclusively_queued"),
                            (9, "not_exclusively_queued")]),
    )
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert entry["reason"] == "claim_skipped:issue_changed_since_plan,not_exclusively_queued"
    assert entry["skipped_issues"] == [7, 8, 9]


@pytest.mark.parametrize("bad", [True, False, 0, -1, "7", 7.0, None])
def test_a_skipped_row_with_a_bad_issue_makes_claims_malformed(bad):
    doc = claims_doc()
    doc["skipped"] = [{"issue": bad, "reason": "x"}]
    rec = claimed_record({"taxonomy": planned_lane(7)}, doc)
    assert rec["module_lanes"]["claims"]["status"] == "malformed"
    assert rec["module_lanes"]["lanes"]["taxonomy"]["reason"] == "claims_malformed"


@pytest.mark.parametrize("skipped", [None, "x", {}, [3], ["x"]])
def test_a_missing_or_non_list_skipped_field_is_malformed(skipped):
    doc = claims_doc()
    if skipped is None:
        del doc["skipped"]
    else:
        doc["skipped"] = skipped
    assert lanes.claim_evidence(doc)["status"] == "malformed"


@pytest.mark.parametrize("row", [{"issue": 7}, {"issue": 7, "reason": ""}, {"issue": 7, "reason": 5}])
def test_a_skipped_row_without_a_usable_reason_is_malformed_the_producer_always_writes_one(row):
    doc = claims_doc()
    doc["skipped"] = [row]
    doc["planned_count"] = 1
    rec = claimed_record({"taxonomy": planned_lane(7)}, doc)
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert rec["module_lanes"]["claims"] == {"status": "malformed", "reason": "claims_skipped_invalid"}
    assert (entry["lane_state"], entry["reason"]) == ("unknown", "claims_malformed")


def test_a_skipped_issue_planned_in_no_lane_leaves_lanes_alone_but_is_recorded():
    rec = claimed_record({"taxonomy": planned_lane(8)}, claims_doc(skipped=[SKIP]))
    assert rec["module_lanes"]["lanes"]["taxonomy"]["reason"] == "planned_unconfirmed"
    assert rec["module_lanes"]["claims"]["skipped"] == [
        {"issue": 7, "reason": "not_exclusively_queued"}]


def test_skipped_does_not_apply_to_an_unplanned_issue_of_a_lane():
    lane_doc = lane("executing", running=[7]) | {"planned": []}
    entry = claimed_record({"taxonomy": lane_doc}, claims_doc(skipped=[SKIP]))[
        "module_lanes"]["lanes"]["taxonomy"]
    assert entry["lane_state"] == "working"


def test_a_skip_appends_a_transition_naming_the_lane():
    gh = FakeGitHub()
    lanes.publish(gh, 1949, claimed_record({"taxonomy": planned_lane(7)}, claims_doc()))
    assert len(gh.created) == 2
    result = lanes.publish(
        gh, 1949, claimed_record({"taxonomy": planned_lane(7)}, claims_doc(skipped=[SKIP])))
    assert len(gh.created) == 3
    assert result["lane_changes"][0]["to"] == {
        "lane_state": "unknown", "reason": "claim_skipped:not_exclusively_queued"}


def test_a_lease_failure_still_overrides_a_skipped_lane():
    rec = claimed_record({"taxonomy": planned_lane(7)}, claims_doc(skipped=[SKIP]),
                         recovery={"errors": [{"issue": 7}]})
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert entry["lane_state"] == "failed"
    assert entry["reason"] == "lease_reconcile_errors:claim_skipped:not_exclusively_queued"


# --- remaining handoff fields that guard against a wrong or stale file ---------


def test_launch_count_must_match_the_confirmed_rows():
    doc = claims_doc(confirmed=[(7, False)])
    doc["launch_count"] = 0
    assert lanes.claim_evidence(doc)["status"] == "malformed"
    doc["launch_count"] = True
    assert lanes.claim_evidence(doc)["status"] == "malformed"


def test_a_claim_file_from_another_run_is_not_trusted():
    doc = claims_doc(confirmed=[(7, False)])
    doc["run_id"] = 999
    rec = claimed_record({"taxonomy": planned_lane(7)}, doc)  # record run_id is "1"
    assert rec["module_lanes"]["claims"] == {"status": "malformed", "reason": "claims_run_mismatch"}
    assert rec["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "unknown"
    doc["run_id"] = 1
    ok = claimed_record({"taxonomy": planned_lane(7)}, doc)
    assert ok["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "working"


# --- the handoff must carry every key the parser relies on ---------------------


def real_handoff():
    """The exact shape oc_swarm_claim.claim_workers() returns, every key present."""
    worker = {
        "issue_number": 7, "reads": [], "writes": ["control-plane"], "dependencies": [],
        "provider_free": False, "lane_executable": False, "acquisition": False,
        "lease_comment_id": 100, "material_fingerprint": "abc123",
    }
    return {
        "schema": "oc.swarm-claim-handoff.v1",
        "run_id": 1,
        "run_attempt": 2,
        "healthy": True,
        "planned_count": 2,
        "launch_count": 1,
        "matrix": {"include": [worker]},
        "confirmed": [worker],
        "provider_free_matrix": {"include": []},
        "provider_matrix": {"include": [worker]},
        "acquisition_matrix": {"include": []},
        "acquisition_launch_count": 0,
        "provider_free_launch_count": 0,
        "provider_launch_count": 1,
        "skipped": [{"issue": 8, "reason": "not_exclusively_queued"}],
        "errors": [],
    }


def test_a_real_shaped_handoff_is_accepted_as_ok():
    evidence = lanes.claim_evidence(real_handoff())
    assert evidence["status"] == "ok" and evidence["confirmed"] == {7: "provider"}
    rec = claimed_record(
        {"taxonomy": planned_lane(7), "literature": planned_lane(8)}, real_handoff())
    out = rec["module_lanes"]["lanes"]
    assert out["taxonomy"]["lane_state"] == "working"
    assert out["literature"]["reason"] == "claim_skipped:not_exclusively_queued"
    assert rec["module_lanes"]["claims"]["status"] == "ok"


def _without(key):
    doc = real_handoff()
    del doc[key]
    return doc


def _with(**kw):
    return {**real_handoff(), **kw}


IDENTITY_CASES = [
    (_without("run_id"), "claims_run_id_missing"),
    (_with(run_id=""), "claims_run_id_missing"),
    (_with(run_id="  "), "claims_run_id_missing"),
    (_with(run_id=None), "claims_run_id_missing"),
    (_with(run_id=True), "claims_run_id_missing"),
    (_with(run_id=0), "claims_run_id_missing"),
    (_with(run_id=99), "claims_run_mismatch"),
    (_with(schema="oc.swarm-claim-handoff.v2"), "claims_schema_mismatch"),
    (_without("schema"), "claims_schema_mismatch"),
    (_without("launch_count"), "claims_launch_count_invalid"),
    (_with(launch_count=0), "claims_launch_count_invalid"),
    (_with(launch_count=2), "claims_launch_count_invalid"),
    (_with(launch_count="1"), "claims_launch_count_invalid"),
    (_with(launch_count=True), "claims_launch_count_invalid"),
    (_with(launch_count=1.0), "claims_launch_count_invalid"),
    (_without("confirmed"), "claims_confirmed_invalid"),
    (_with(confirmed="x"), "claims_confirmed_invalid"),
    (_without("skipped"), "claims_skipped_invalid"),
    (_with(skipped={}), "claims_skipped_invalid"),
    (_without("errors"), "claims_errors_invalid"),
    (_with(errors=None), "claims_errors_invalid"),
    # one issue cannot be confirmed and also skipped/errored, nor confirmed twice
    (_with(skipped=[{"issue": 7, "reason": "x"}]), "claims_rows_conflict"),
    (_with(errors=[{"issue": 7, "phase": "p", "reason": "r"}]), "claims_rows_conflict"),
]


@pytest.mark.parametrize(("doc", "reason"), IDENTITY_CASES)
def test_an_incomplete_or_foreign_handoff_is_malformed_and_never_marks_a_lane_working(doc, reason):
    rec = claimed_record({"taxonomy": planned_lane(7)}, doc)
    claims = rec["module_lanes"]["claims"]
    entry = rec["module_lanes"]["lanes"]["taxonomy"]
    assert claims == {"status": "malformed", "reason": reason}
    assert entry["lane_state"] == "unknown" and entry["lane_state"] != "working"


def test_duplicate_confirmed_rows_are_malformed():
    doc = real_handoff()
    doc["confirmed"] = doc["confirmed"] * 2
    doc["launch_count"] = 2
    assert lanes.claim_evidence(doc) == {"status": "malformed", "reason": "claims_rows_conflict"}


def test_a_string_run_id_that_matches_is_accepted():
    assert lanes.claim_evidence(_with(run_id="1"))["status"] == "ok"


# --- one strict validator per producer row type + an exhaustive mutation fuzz ---

class _SelectiveGitHub(ClaimGitHub):
    """The claim fixtures' fake, failing the lease receipt of one issue only."""

    def __init__(self, rows, fail_issue):
        super().__init__(rows)
        self.fail_issue = fail_issue

    def __call__(self, args, payload=None):
        if args[:3] == ["api", "--method", "POST"] and f"/issues/{self.fail_issue}/" in args[3]:
            raise subprocess.TimeoutExpired("redacted", 30)
        return super().__call__(args, payload)


def _worker(number, *, free=False, writes="control-plane"):
    return {"issue_number": number, "reads": [], "writes": [writes], "dependencies": [],
            "provider_free": free, "lane_executable": free, "acquisition": False}


def producer_handoff():
    """Built by the real claim_workers() on the claim tests' own fixtures:
    1 confirmed (provider), 2 skipped, 3 error, 4 confirmed (provider-free)."""
    rows = [
        claim_issue(1),
        claim_issue(2, labels=["oc-blocked"]),
        claim_issue(3),
        claim_issue(4, body="OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"),
    ]
    plan = {"workers": [_worker(1), _worker(2), _worker(3), _worker(4, free=True, writes="literature")]}
    api = _SelectiveGitHub(rows, fail_issue=3)
    # Only issue 2's labels are changed in the snapshot the claim step re-reads.
    api.rows[2]["labels"] = ["oc-blocked"]
    return claim_workers(plan, {"issues": rows}, repository="owner/repo", run_id=1,
                         run_attempt=2, call=api)


def producer_abort_handoff():
    """Plan-validation failure: the claim step processes nobody."""
    rows = [claim_issue(1), claim_issue(2)]
    plan = {"workers": [_worker(1), {**_worker(2), "lane_executable": True}]}
    return claim_workers(plan, {"issues": rows}, repository="owner/repo", run_id=1,
                         call=ClaimGitHub(rows))


FUZZ_LANES = {
    "taxonomy": planned_lane(1),
    "literature": planned_lane(2),
    "matrix-id": planned_lane(3),
    "pollinator": planned_lane(4),
    "conservation": lane("empty"),
}


def _lane_view(handoff):
    rec = claimed_record(FUZZ_LANES, handoff)
    return rec["module_lanes"]["claims"], rec["module_lanes"]["lanes"]


def test_the_fixture_is_a_real_producer_handoff_and_is_accepted_ok():
    handoff = producer_handoff()
    assert [r["issue_number"] for r in handoff["confirmed"]] == [1, 4]
    assert handoff["skipped"] == [{"issue": 2, "reason": "not_exclusively_queued"}]
    assert [e["issue"] for e in handoff["errors"]] == [3]
    claims, out = _lane_view(handoff)
    assert claims["status"] == "ok"
    assert out["taxonomy"]["reason"] == "claim_confirmed:provider"
    assert out["pollinator"]["reason"] == "claim_confirmed:provider_free"
    assert out["literature"]["reason"] == "claim_skipped:not_exclusively_queued"
    assert out["matrix-id"]["reason"] == "claim_error:planned_unconfirmed"
    abort = producer_abort_handoff()
    assert abort["confirmed"] == [] and abort["errors"][0]["phase"] == "plan_validation"
    assert _lane_view(abort)[0]["status"] == "ok"


_MISSING = object()
_VALUES = [
    _MISSING, None, True, False, 0, -1, 2**63, 10**9, 1.5, 1.0, "", " ", "x", "1",
    [], [1], {}, {"a": 1},
]
#: Top-level keys the parser never reads for a lane's state. Mutating them cannot
#: change a lane, so an ok result with changed lanes would be a bug elsewhere:
#: run_attempt (retry counter), healthy (== not errors), matrix / provider_matrix /
#: provider_free_matrix / acquisition_matrix and the three per-kind launch counts
#: (copies of `confirmed` split by kind; the kind is derived from `confirmed`).
IRRELEVANT_TOP = {
    "run_attempt", "healthy", "matrix", "provider_matrix", "provider_free_matrix",
    "acquisition_matrix", "acquisition_launch_count", "provider_free_launch_count",
    "provider_launch_count",
}
#: Row fields whose *valid* values are the evidence itself, so substituting another
#: valid value is a different (still well-formed) handoff, not a parser hole:
#: issue numbers (attribution), skipped reason (text), the two kind booleans.
def _legit_substitution(section, key, value):
    if key in {"issue_number", "issue"}:
        return lanes._issue_no(value) is not None
    if (section, key) == ("skipped", "reason"):
        return isinstance(value, str) and bool(value.strip())
    return key in {"lane_executable", "acquisition"} and isinstance(value, bool)


def _mutations(handoff):
    for key in handoff:
        for value in _VALUES:
            mutated = deepcopy(handoff)
            if value is _MISSING:
                del mutated[key]
            else:
                mutated[key] = deepcopy(value)
            yield ("top", key, value), key in IRRELEVANT_TOP, mutated
    for section in ("confirmed", "skipped", "errors"):
        for index, row in enumerate(handoff[section]):
            for key in row:
                for value in _VALUES:
                    mutated = deepcopy(handoff)
                    if value is _MISSING:
                        del mutated[section][index][key]
                    else:
                        mutated[section][index][key] = deepcopy(value)
                    legit = value is not _MISSING and _legit_substitution(section, key, value)
                    yield (section, key, value), legit, mutated
            mutated = deepcopy(handoff)
            del mutated[section][index]
            yield (section, "<row deleted>", _MISSING), False, mutated
            mutated = deepcopy(handoff)
            mutated[section][index] = "not-a-row"
            yield (section, "<row not a dict>", "not-a-row"), False, mutated


@pytest.mark.parametrize("make", [producer_handoff, producer_abort_handoff])
def test_no_mutated_handoff_that_still_parses_ok_can_change_a_lane(make):
    handoff = make()
    base_claims, base_lanes = _lane_view(handoff)
    assert base_claims["status"] == "ok"
    checked = still_ok = 0
    for label, allowed, mutated in _mutations(handoff):
        checked += 1
        claims, out = _lane_view(mutated)
        if claims["status"] != "ok":
            # Fail closed: every lane with a planned issue is unknown, nothing is working.
            assert claims["status"] == "malformed" and claims["reason"], label
            for name in ("taxonomy", "literature", "matrix-id", "pollinator"):
                assert out[name]["lane_state"] == "unknown", label
            continue
        still_ok += 1
        if not allowed:
            assert out == base_lanes, label
    assert checked > 300 and still_ok > 0


# Producer-exact row contracts, one case per rule.
ROW_CASES = [
    ("confirmed", "issue_number", "claims_confirmed_invalid"),
    ("confirmed", "reads", "claims_confirmed_invalid"),
    ("confirmed", "writes", "claims_confirmed_invalid"),
    ("confirmed", "dependencies", "claims_confirmed_invalid"),
    ("confirmed", "provider_free", "claims_confirmed_invalid"),
    ("confirmed", "lane_executable", "claims_confirmed_invalid"),
    ("confirmed", "acquisition", "claims_confirmed_invalid"),
    ("confirmed", "lease_comment_id", "claims_confirmed_invalid"),
    ("confirmed", "material_fingerprint", "claims_confirmed_invalid"),
    ("skipped", "issue", "claims_skipped_invalid"),
    ("skipped", "reason", "claims_skipped_invalid"),
    ("errors", "issue", "claims_errors_invalid"),
    ("errors", "phase", "claims_errors_invalid"),
    ("errors", "reason", "claims_errors_invalid"),
]


@pytest.mark.parametrize(("section", "key", "reason"), ROW_CASES)
@pytest.mark.parametrize("how", ["delete", "none", "str-for-bool-or-int", "empty-string"])
def test_every_producer_row_field_is_required_with_its_exact_type(section, key, reason, how):
    handoff = producer_handoff()
    row = handoff[section][0]
    if how == "delete":
        del row[key]
    elif how == "none":
        row[key] = None
    elif how == "str-for-bool-or-int":
        row[key] = "true" if isinstance(row[key], bool | int | list) else 5
    else:
        row[key] = ""
    assert lanes.claim_evidence(handoff) == {"status": "malformed", "reason": reason}


def test_planned_count_must_account_for_every_outcome_unless_planning_aborted():
    handoff = producer_handoff()
    handoff["planned_count"] = 3
    assert lanes.claim_evidence(handoff)["reason"] == "claims_planned_count_invalid"
    del handoff["planned_count"]
    assert lanes.claim_evidence(handoff)["reason"] == "claims_planned_count_invalid"
    abort = producer_abort_handoff()
    abort["confirmed"] = deepcopy(producer_handoff()["confirmed"][:1])
    abort["launch_count"] = 1
    assert lanes.claim_evidence(abort)["status"] == "malformed"


def test_an_unavailable_claim_file_makes_only_planned_lanes_unknown():
    rec = record(with_lanes({"taxonomy": planned_lane(7), "literature": lane("executing", running=[2])}))
    out = rec["module_lanes"]["lanes"]
    assert out["taxonomy"]["reason"] == "claims_unavailable"
    assert out["literature"]["lane_state"] == "working"


# --- precedence model: one table, checked against an independent oracle --------

def _oracle(running, validating, status, outcome, lease):
    """Plain precedence table for one lane. Rules, highest first:
    a. lease evidence on a lane issue: error -> failed, recovery -> recovering
       (always applies, wraps whatever b-e decided).
    b. running or validating issues in the snapshot: working, whatever the claim
       handoff says (a caveat naming an unresolved planned issue is appended).
    c. a confirmed claim on the planned issue: working.
    d. only otherwise, a planned issue whose outcome is unresolved (no usable
       handoff, or skipped): unknown.
    e. otherwise the base mapping: planned but not launched -> idle.
    A claim error on the lane's issue prefixes the reason without changing state.
    """
    planned = outcome != "none"
    unresolved = None
    if planned and status == "malformed":
        unresolved = "claims_malformed"
    elif planned and status == "unavailable":
        unresolved = "claims_unavailable"
    elif planned and outcome == "skipped":
        unresolved = "claim_skipped:not_exclusively_queued"
    confirmed = status == "ok" and outcome == "confirmed"
    if running:                                   # b
        state, reason = "working", "module_state:executing"
    elif validating:                              # b
        state = "working"
        reason = "validating_issues_present" if planned else "module_state:validating"
    elif confirmed:                               # c
        state, reason = "working", "claim_confirmed:provider"
    elif unresolved:                              # d
        state, reason = "unknown", unresolved
    elif planned:                                 # e: good handoff, nothing launched
        state, reason = "idle", "planned_unconfirmed"
    else:                                         # e: nothing planned
        state, reason = "idle", "module_state:empty"
    if (running or validating) and confirmed:
        reason += ";claim_confirmed:provider"
    if (running or validating) and unresolved:
        reason += ";" + unresolved
    if status == "ok" and outcome == "errored":
        reason = "claim_error:" + reason
    if lease in {"error", "both"}:                # a: error wins over recovery
        state, reason = "failed", "lease_reconcile_errors:" + reason
    elif lease == "recovered":                    # a
        state, reason = "recovering", "lease_recovered:" + reason
    return state, reason


def _claims_for(status, outcome):
    if status == "unavailable":
        return None
    if status == "malformed":
        return "garbage"
    return {
        "confirmed": claims_doc(confirmed=[(7, False)]),
        "skipped": claims_doc(skipped=[(7, "not_exclusively_queued")]),
        "errored": claims_doc(errors=[7]),
    }.get(outcome, claims_doc())


PRECEDENCE_CASES = [
    (running, validating, status, outcome, lease)
    for running, validating, status, outcome, lease in itertools.product(
        (False, True),
        (False, True),
        ("ok", "malformed", "unavailable"),
        ("none", "confirmed", "skipped", "errored", "absent"),
        ("none", "recovered", "error", "both"),
    )
    # Outcomes are only distinguishable with a good handoff; without one, a planned
    # issue is simply planned. A lease needs a lane issue to name.
    if (status == "ok" or outcome in {"none", "absent"})
    and (lease == "none" or running or validating or outcome != "none")
]


def test_the_precedence_table_covers_the_whole_cross_product():
    assert len(PRECEDENCE_CASES) == 135


@pytest.mark.parametrize(("running", "validating", "status", "outcome", "lease"), PRECEDENCE_CASES)
def test_lane_state_follows_the_documented_precedence_model(running, validating, status, outcome, lease):
    planned = outcome != "none"
    entry = lane(
        "executing" if running else "replenishable" if planned else "validating" if validating else "empty",
        running=[10] if running else [],
        validating=[11] if validating else [],
        replenishable=[7] if planned else [],
    ) | {"planned": [7] if planned else []}
    number = 10 if running else 11 if validating else 7
    recovery = {
        "none": None,
        "recovered": {"recovered": [{"issue_number": number}]},
        "error": {"errors": [{"issue": number}]},
        "both": {"recovered": [{"issue_number": number}], "errors": [{"issue": number}]},
    }[lease]
    got = claimed_record({"taxonomy": entry}, _claims_for(status, outcome), recovery)[
        "module_lanes"]["lanes"]["taxonomy"]
    assert (got["lane_state"], got["reason"]) == _oracle(running, validating, status, outcome, lease)
