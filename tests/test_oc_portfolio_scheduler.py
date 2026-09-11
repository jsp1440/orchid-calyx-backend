"""Behavioural contract for priority-aware five-lane portfolio selection.

These tests exercise `scripts/oc_portfolio_scheduler.py` directly rather than
grepping the workflow, so the scheduling policy itself is proven: priority
ordering, capacity from live execution leases, durable-PR duplicate suppression,
bounded repair authorization and deterministic starvation protection.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/oc_portfolio_scheduler.py")

_spec = importlib.util.spec_from_file_location("oc_portfolio_scheduler", SCRIPT)
sched = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sched)

NOW = "2026-08-21T06:00:00Z"


def issue(number: int, *, title: str = "", labels=("oc-queued",), created: str = "2026-08-21T05:00:00Z") -> dict:
    return {
        "number": number,
        "title": title or f"ISSUE-{number}",
        "labels": [{"name": name} for name in labels],
        "createdAt": created,
    }


def plan(issues, pull_requests=(), max_active_lanes=5, now=NOW) -> dict:
    return sched.build_plan(
        {
            "issues": list(issues),
            "pull_requests": list(pull_requests),
            "max_active_lanes": max_active_lanes,
            "now": now,
        }
    )


# --- priority resolution -----------------------------------------------------

def test_priority_comes_from_the_canonical_leading_title_token():
    assert sched.resolve_priority({"title": "P0 OC-COMPLETE-001 — scheduler", "labels": []}) == (0, "title")
    assert sched.resolve_priority({"title": "[P2] federation expansion", "labels": []}) == (2, "title")


def test_unclassified_work_is_not_mined_from_body_text():
    resolved = sched.resolve_priority(
        {"title": "ORCHESTRATION-EVENT-DRIVEN-001 — trigger follow-through", "labels": []}
    )
    assert resolved == (sched.DEFAULT_PRIORITY, "default")


def test_unclassified_work_outranks_p5_idle_but_yields_to_every_explicit_band():
    result = plan(
        [
            issue(60, title="P5 IDLE-CAPACITY — background", created="2026-08-01T00:00:00Z"),
            issue(61, title="ORCHESTRATION-EVENT-DRIVEN-001 — unclassified", created="2026-08-02T00:00:00Z"),
            issue(62, title="P4 explicit operational", created="2026-08-03T00:00:00Z"),
        ],
        max_active_lanes=1,
    )
    assert [row["number"] for row in result["ranking"]] == [62, 61, 60]
    assert result["selected_numbers"] == [62]


def test_explicit_priority_label_outranks_the_title_token():
    # Both directions: a label must win whether it raises or lowers the title's claim.
    assert sched.resolve_priority(
        {"title": "P5 IDLE-CAPACITY — something", "labels": [{"name": "oc-p1"}]}
    ) == (1, "label")
    assert sched.resolve_priority(
        {"title": "P1 looks urgent", "labels": [{"name": "oc-p3"}]}
    ) == (3, "label")


def test_a_title_token_never_promotes_work_over_its_explicit_label():
    result = plan(
        [
            issue(70, title="P1 looks urgent", labels=("oc-queued", "oc-p3")),
            issue(71, title="P2 genuinely second", labels=("oc-queued", "oc-p2")),
        ],
        max_active_lanes=1,
    )
    assert result["selected_numbers"] == [71]


def test_priority_label_backfill_targets_only_orchestration_issues():
    fixes = sched.priority_label_fixes(
        [
            issue(1083, title="P0 OC-COMPLETE-001", labels=("oc-queued",)),
            issue(9, title="P0 unrelated repository issue", labels=("bug",)),
            issue(1082, title="P1 CALYX", labels=("oc-queued", "oc-p1")),
        ]
    )
    assert [f["number"] for f in fixes] == [1083]
    assert fixes[0]["add"] == "oc-p0"


# --- ordering ----------------------------------------------------------------

def test_p0_outranks_p1():
    result = plan(
        [
            issue(200, title="P1 later work", created="2026-08-01T00:00:00Z"),
            issue(201, title="P0 newer work", created="2026-08-21T05:00:00Z"),
        ],
        max_active_lanes=1,
    )
    assert result["selected_numbers"] == [201]


def test_canonical_stabilization_outranks_older_p0_and_freezes_expansion():
    result = sched.build_plan(
        {
            "issues": [
                issue(1177, title="P0 older security work", created="2026-08-25T00:00:00Z"),
                issue(1193, title="P0 canonical stabilization", created="2026-08-26T00:00:00Z"),
                issue(1195, title="P0 optional expansion", created="2026-08-24T00:00:00Z"),
            ],
            "max_active_lanes": 3,
            "stabilization_issue": 1193,
            "now": NOW,
        }
    )
    assert result["selected_numbers"] == [1193]
    assert {row["number"] for row in result["suppressed"] if row["reason"] == "stabilization-freeze"} == {1177, 1195}


def test_stabilization_freeze_releases_when_canonical_mission_is_not_eligible():
    result = sched.build_plan(
        {
            "issues": [
                issue(1193, labels=("oc-validating",), title="P0 canonical stabilization"),
                issue(1177, title="P0 next work"),
            ],
            "max_active_lanes": 1,
            "stabilization_issue": 1193,
            "now": NOW,
        }
    )
    assert result["selected_numbers"] == [1177]


def test_p1_outranks_p2():
    result = plan(
        [
            issue(300, title="P2 older work", created="2026-08-01T00:00:00Z"),
            issue(301, title="P1 newer work", created="2026-08-21T05:00:00Z"),
        ],
        max_active_lanes=1,
    )
    assert result["selected_numbers"] == [301]


def test_equal_priority_is_ordered_oldest_eligible_first_then_issue_number():
    result = plan(
        [
            issue(402, title="P1 c", created="2026-08-20T00:00:00Z"),
            issue(400, title="P1 a", created="2026-08-19T00:00:00Z"),
            issue(401, title="P1 b", created="2026-08-19T00:00:00Z"),
        ],
        max_active_lanes=3,
    )
    assert result["selected_numbers"] == [400, 401, 402]


def test_selection_is_deterministic_under_input_reordering():
    # All inside the fairness window, so this isolates strict priority ordering.
    issues = [
        issue(500, title="P2 x", created="2026-08-20T10:00:00Z"),
        issue(501, title="P0 y", created="2026-08-20T14:00:00Z"),
        issue(502, title="P1 z", created="2026-08-20T12:00:00Z"),
    ]
    first = plan(issues, max_active_lanes=2)["selected_numbers"]
    second = plan(list(reversed(issues)), max_active_lanes=2)["selected_numbers"]
    assert first == second == [501, 502]


# --- the regression this change exists for -----------------------------------

LEGACY_BACKLOG = (1030, 1029, 1025, 1026, 1027, 1008, 1021, 1022, 1023, 1024)


def live_portfolio() -> list[dict]:
    """The live portfolio shape that exposed the starvation defect."""
    return [
        issue(1023, title="ORCHESTRATION-EVENT-DRIVEN-001 — trigger follow-through", created="2026-08-18T22:09:06Z"),
        issue(1081, title="P5 IDLE-CAPACITY — OC-AI-DS-001 learning engine", created="2026-08-21T00:44:49Z"),
        issue(1082, title="P1 CALYX-SYNTHESIS-001 — TeachingSynthesis", created="2026-08-21T00:58:19Z"),
        issue(1083, title="P0 OC-COMPLETE-001 — priority-aware five-lane portfolio scheduler", created="2026-08-21T02:11:07Z"),
        issue(1084, title="P0 OC-COMPLETE-002 — Hassler release intake", created="2026-08-21T02:11:20Z"),
        issue(1085, title="P0 OC-COMPLETE-003 — coverage/freshness matrix", created="2026-08-21T02:11:30Z"),
        issue(1086, title="P2 OC-COMPLETE-004 — federation expansion", created="2026-08-21T02:11:43Z"),
        issue(1089, title="P1 OC-COMPLETE-009 — capability mining", created="2026-08-21T02:25:41Z"),
    ]


def test_new_p0_work_is_not_starved_by_the_former_legacy_backlog():
    result = plan(live_portfolio())
    selected = result["selected_numbers"]
    # Both P0 issues in distinct canonical lanes (L5 scheduler, L2 Hassler) must be
    # dispatched.  Under lane-aware enforcement 1085 (also L2) cannot run
    # simultaneously with 1084, so only two of the three original P0s are selected.
    assert 1083 in selected   # P0 L5 — portfolio scheduler
    assert 1084 in selected   # P0 L2 — Hassler release
    assert 1085 not in selected  # P0 L2 — blocked: L2 already held by 1084
    # The legacy backlog still does not capture the first three dispatch slots.
    legacy_first_three = [n for n in selected[:3] if n in LEGACY_BACKLOG]
    assert legacy_first_three == []


def test_legacy_queued_work_still_competes_under_the_same_policy():
    ranking = [row["number"] for row in plan(live_portfolio())["ranking"]]
    assert 1023 in ranking


def test_no_hard_coded_issue_number_list_remains_in_the_policy():
    source = SCRIPT.read_text()
    assert "BACKLOG" not in source
    for number in LEGACY_BACKLOG:
        assert f"{number}" not in source


# --- capacity ----------------------------------------------------------------

def test_five_total_active_lanes_is_the_upper_bound():
    issues = [issue(600 + n, title="P0 work", created=f"2026-08-20T0{n}:00:00Z") for n in range(9)]
    result = plan(issues)
    assert result["max_active_lanes"] == 5
    assert result["available_capacity"] == 5
    assert len(result["selected_numbers"]) == 5


def test_three_running_lanes_leave_capacity_for_exactly_two_more():
    running = [issue(700 + n, title="P0 running", labels=("oc-running",)) for n in range(3)]
    queued = [issue(710 + n, title="P0 queued", created=f"2026-08-20T0{n}:00:00Z") for n in range(4)]
    result = plan(running + queued)
    assert result["active_lane_count"] == 3
    assert result["available_capacity"] == 2
    assert result["selected_numbers"] == [710, 711]


def test_full_lanes_dispatch_nothing():
    running = [issue(800 + n, labels=("oc-running",)) for n in range(5)]
    result = plan(running + [issue(810, title="P0 queued")])
    assert result["available_capacity"] == 0
    assert result["selected_numbers"] == []


def test_oc_validating_does_not_consume_an_execution_slot():
    validating = [issue(900 + n, labels=("oc-validating",)) for n in range(4)]
    queued = [issue(910 + n, title="P0 queued", created=f"2026-08-20T0{n}:00:00Z") for n in range(5)]
    result = plan(validating + queued)
    assert result["active_lane_count"] == 0
    assert result["available_capacity"] == 5
    assert len(result["selected_numbers"]) == 5


def test_runtime_backed_off_work_is_not_ranked_or_selected():
    """Parked by the repository-wide Claude runtime circuit; not a candidate.

    The workflow's pre-dispatch re-read also skips these, but a planner that
    ranked them would hand back a selection the dispatch loop then refuses,
    silently wasting a lane.
    """
    parked = issue(1900, title="P0 parked by the runtime circuit",
                   labels=("oc-queued", "oc-runtime-backoff"))
    result = plan([parked, issue(1901, title="P3 genuinely eligible")])
    assert result["selected_numbers"] == [1901]
    assert 1900 not in [row["number"] for row in result["ranking"]]
    assert {"number": 1900, "reason": "oc-runtime-backoff"}.items() <= next(
        row for row in result["suppressed"] if row["number"] == 1900
    ).items()


def test_repair_backoff_is_not_ranked_or_selected():
    parked = issue(1902, title="P0 exhausted repair",
                   labels=("oc-queued", "oc-repair", "oc-repair-backoff"))
    result = plan([parked, issue(1903, title="P3 eligible")])
    assert result["selected_numbers"] == [1903]
    assert next(row for row in result["suppressed"] if row["number"] == 1902)["reason"] == "oc-repair-backoff"


def test_oc_blocked_and_owner_gate_do_not_consume_an_execution_slot():
    held = [
        issue(1000, labels=("oc-blocked",)),
        issue(1001, labels=("oc-owner-gate",)),
        issue(1002, labels=("oc-queued", "oc-blocked"), title="P0 externally blocked"),
        issue(1003, labels=("oc-queued", "oc-owner-gate"), title="P0 owner gated"),
    ]
    result = plan(held + [issue(1004, title="P2 open work")])
    assert result["active_lane_count"] == 0
    assert result["available_capacity"] == 5
    assert result["selected_numbers"] == [1004]
    reasons = {row["number"]: row["reason"] for row in result["suppressed"]}
    assert reasons[1002] == "oc-blocked"
    assert reasons[1003] == "oc-owner-gate"


# --- durable PR lineage / repair ---------------------------------------------

DURABLE_PR = {"number": 77, "body": "slice\n\nOC-AUTO-ISSUE: #1100\nOC-AUTO-REQUEUE: false\n"}


def test_durable_pr_lineage_suppresses_duplicate_dispatch():
    result = plan([issue(1100, title="P0 delivered slice")], [DURABLE_PR])
    assert result["selected_numbers"] == []
    assert result["suppressed"] == [
        row for row in result["suppressed"] if row["number"] == 1100 and row["reason"] == "durable-pr"
    ]
    assert result["suppressed"][0]["durable_pr"] == 77


def test_oc_repair_authorizes_exactly_one_bounded_redispatch_over_a_durable_pr():
    result = plan([issue(1100, title="P0 delivered slice", labels=("oc-queued", "oc-repair"))], [DURABLE_PR])
    assert result["selected_numbers"] == [1100]
    assert result["selected"][0]["selection_reason"] == "repair-reserved"
    # Repair without the queue lease is not selectable; the workflow heals that
    # orphaned state back into oc-queued before selection runs.
    orphaned = plan([issue(1100, title="P0 delivered slice", labels=("oc-repair",))], [DURABLE_PR])
    assert orphaned["selected_numbers"] == []


def test_repair_keeps_a_reserved_lane_against_a_stream_of_new_p0_work():
    new_p0 = [issue(1200 + n, title="P0 fresh", created=f"2026-08-21T0{n}:00:00Z") for n in range(8)]
    repair = issue(1150, title="P3 failed exact head", labels=("oc-queued", "oc-repair"))
    result = plan(new_p0 + [repair])
    assert 1150 in result["selected_numbers"]
    assert len(result["selected_numbers"]) == 5
    assert sum(1 for row in result["selected"] if row["selection_reason"] == "repair-reserved") == 1


def test_a_running_lease_is_never_redispatched():
    result = plan([issue(1300, title="P0 already leased", labels=("oc-queued", "oc-running"))])
    assert result["selected_numbers"] == []
    assert result["active_lane_count"] == 1


def test_completed_work_is_not_redispatched():
    done = issue(1400, title="P0 finished", labels=("oc-queued", "oc-done"))
    closed = dict(issue(1401, title="P0 closed"), state="CLOSED")
    result = plan([done, closed, issue(1402, title="P4 real work")])
    assert result["selected_numbers"] == [1402]
    assert 1401 not in [row["number"] for row in result["suppressed"]]


# --- fairness / idle capacity ------------------------------------------------

def test_fairness_reserves_one_lane_for_work_strict_priority_would_leave_behind():
    starved = issue(1500, title="P3 long waiting", created="2026-08-15T00:00:00Z")
    flood = [issue(1510 + n, title="P0 fresh", created=f"2026-08-21T0{n}:00:00Z") for n in range(9)]
    result = plan([starved] + flood)
    assert 1500 in result["selected_numbers"]
    assert result["fairness_reservation"] == 1500
    # Fairness costs exactly one lane; the rest still go to strict priority.
    assert len(result["selected_numbers"]) == 5
    assert sum(1 for row in result["selected"] if row["selection_reason"] == "fairness") == 1


def test_fairness_never_lets_stale_work_outrank_fresh_p0_for_the_primary_lanes():
    starved = issue(1600, title="P3 long waiting", created="2026-06-01T00:00:00Z")
    fresh_p0 = [issue(1610 + n, title="P0 fresh", created=f"2026-08-21T0{n}:00:00Z") for n in range(4)]
    result = plan([starved] + fresh_p0)
    assert result["selected_numbers"][:4] == [1610, 1611, 1612, 1613]
    assert result["selected_numbers"][4] == 1600


def test_recently_queued_work_does_not_claim_the_fairness_lane():
    recent = issue(1700, title="P3 recent", created="2026-08-21T05:30:00Z")
    flood = [issue(1710 + n, title="P0 fresh", created=f"2026-08-21T0{n}:00:00Z") for n in range(9)]
    result = plan([recent] + flood)
    assert result["fairness_reservation"] is None
    assert 1700 not in result["selected_numbers"]


def test_p5_idle_work_is_admitted_only_when_no_higher_priority_work_waits():
    idle = issue(1800, title="P5 IDLE-CAPACITY — background", created="2026-08-01T00:00:00Z")
    busy = plan([idle] + [issue(1810 + n, title="P0 fresh", created=f"2026-08-21T0{n}:00:00Z") for n in range(9)])
    assert 1800 not in busy["selected_numbers"]

    quiet = plan([idle, issue(1811, title="P1 one item")])
    assert quiet["selected_numbers"] == [1811, 1800]
    assert quiet["selected"][1]["selection_reason"] == "idle-capacity"


# --- CLI ---------------------------------------------------------------------

def test_cli_emits_a_json_plan_and_a_selected_number_list(tmp_path):
    payload = tmp_path / "snapshot.json"
    payload.write_text(json.dumps({"issues": live_portfolio(), "pull_requests": [], "now": NOW}))

    plan_out = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(payload), "--mode", "plan"],
        capture_output=True, text=True, check=True,
    ).stdout
    parsed = json.loads(plan_out)
    assert parsed["max_active_lanes"] == 5

    selected_out = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(payload), "--mode", "selected"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert [int(line) for line in selected_out.split()] == parsed["selected_numbers"]


# --- recovery-width regression contract ---------------------------------------

def test_max_active_lanes_constant_is_five():
    """Lock the five-lane capacity restored in the PR that fixed the dispatch freeze."""
    assert sched.MAX_ACTIVE_LANES == 5


# --- lane-aware capacity enforcement -----------------------------------------

def test_five_issues_in_the_same_lane_cannot_all_be_selected():
    # Five L1 (Brain) issues compete for five available slots.
    # Lane enforcement caps L1 at one active execution at a time.
    issues = [
        issue(2000 + n, title=f"P0 brain reasoning ledger work {n}",
              created=f"2026-08-20T0{n}:00:00Z")
        for n in range(5)
    ]
    result = plan(issues)
    assert result["available_capacity"] == 5
    assert len(result["selected_numbers"]) == 1
    assert result["selected_numbers"] == [2000]


def test_independent_issues_across_five_lanes_fill_all_slots():
    # One issue per canonical lane — all five slots can be filled simultaneously.
    issues = [
        issue(2100, title="P0 brain reasoning ledger mission"),
        issue(2101, title="P0 taxonomy occurrence hassler pipeline"),
        issue(2102, title="P0 literature image mycorrhiza pipeline"),
        issue(2103, title="P0 frontend atlas vision operator"),
        issue(2104, title="P0 deploy scheduler orchestrat canary"),
    ]
    result = plan(issues)
    assert result["available_capacity"] == 5
    assert set(result["selected_numbers"]) == {2100, 2101, 2102, 2103, 2104}


def test_already_running_lane_blocks_same_lane_from_being_selected():
    running = issue(2200, title="P0 brain reasoning active", labels=("oc-running",))
    queued_same_lane = issue(2201, title="P0 brain ledger queued")
    queued_other_lane = issue(2202, title="P0 taxonomy occurrence queued")
    result = plan([running, queued_same_lane, queued_other_lane])
    assert result["active_lane_count"] == 1
    assert 2201 not in result["selected_numbers"], "L1 already held by oc-running issue"
    assert 2202 in result["selected_numbers"], "L2 is free and must be selected"


def test_no_duplicate_leases_under_lane_enforcement():
    # Three L1 issues: at most one gets a lease; no issue number appears twice.
    issues = [issue(2300 + n, title=f"P0 brain reasoning work {n}") for n in range(3)]
    result = plan(issues, max_active_lanes=5)
    selected = result["selected_numbers"]
    assert len(selected) == len(set(selected)), "each issue leased at most once"
    assert len(selected) <= 1, "lane enforcement: at most one L1 issue dispatched"


def test_repair_backoff_still_excluded_with_lane_enforcement():
    parked = issue(2400, title="P0 brain reasoning exhausted",
                   labels=("oc-queued", "oc-repair-backoff"))
    eligible_other = issue(2401, title="P0 taxonomy occurrence work")
    result = plan([parked, eligible_other])
    assert 2400 not in result["selected_numbers"]
    assert 2401 in result["selected_numbers"]


def test_fairness_still_works_across_lane_boundaries():
    # A P3 L2 issue starved for six days competes against nine fresh P0 L1 issues.
    # Lane enforcement limits L1 to one slot; fairness reserves a slot for the
    # P3 L2 issue that strict priority would otherwise leave behind.
    starved_l2 = issue(2500, title="P3 taxonomy occurrence starved",
                       created="2026-08-15T00:00:00Z")
    flood_l1 = [
        issue(2510 + n, title=f"P0 brain reasoning fresh {n}",
              created=f"2026-08-21T0{n}:00:00Z")
        for n in range(9)
    ]
    result = plan([starved_l2] + flood_l1)
    assert 2500 in result["selected_numbers"]
    assert result["fairness_reservation"] == 2500
    l1_selected = [n for n in result["selected_numbers"] if 2510 <= n < 2519]
    assert len(l1_selected) == 1, "lane enforcement caps L1 at one concurrent dispatch"


def test_lane_blocked_fairness_candidate_releases_slot_to_other_eligible_work():
    # Regression: when the fairness candidate shares a lane with a priority
    # selection, the reserved slot must be released to the next eligible
    # conflict-free candidate rather than left idle.
    #
    # Setup: 4 P0 issues fill L1/L2/L3/L5, leaving L4 free.  The only
    # long-waiting (P4) issue is also in L5, so its fairness slot is blocked.
    # The reclaim loop must fill capacity with the eligible L4 issue.
    fairness_l5 = issue(3000, title="P4 canary provider dispatch long-wait",
                        created="2026-08-01T00:00:00Z")
    priority_l5 = issue(3001, title="P0 deploy scheduler canary")
    priority_l2 = issue(3002, title="P0 taxonomy occurrence hassler")
    priority_l3 = issue(3003, title="P0 literature image media pipeline")
    priority_l1 = issue(3004, title="P0 brain reasoning ledger")
    eligible_l4 = issue(3005, title="P2 frontend atlas vision operator")
    result = plan([fairness_l5, priority_l5, priority_l2, priority_l3, priority_l1, eligible_l4])
    assert result["fairness_reservation"] == 3000, "long-waiting L5 issue must be identified as fairness candidate"
    assert 3000 not in result["selected_numbers"], "blocked fairness candidate must not be force-inserted"
    assert set(result["selected_numbers"]) == {3001, 3002, 3003, 3004, 3005}
    assert len(result["selected_numbers"]) == 5, "reclaimed slot must fill eligible L4 work; capacity must not be wasted"
