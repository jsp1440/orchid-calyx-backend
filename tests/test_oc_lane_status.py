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


def claims_doc(confirmed=(), errors=()):
    return {
        "schema": "oc.swarm-claim-handoff.v1",
        "confirmed": [
            {"issue_number": n, "lane_executable": free, "acquisition": False,
             "lease_comment_id": 900 + n}
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


def test_missing_claims_are_explicitly_unavailable_and_keep_the_old_mapping():
    doc = with_lanes({"taxonomy": planned_lane(7)})
    rec = record(doc)
    assert rec["module_lanes"]["claims"] == {"status": "unavailable", "reason": "claims_missing"}
    assert rec["module_lanes"]["lanes"]["taxonomy"]["reason"] == "module_state:replenishable"
    assert rec["module_lanes"]["lanes"]["taxonomy"]["lane_state"] == "idle"


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
