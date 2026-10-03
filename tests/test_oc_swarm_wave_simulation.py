"""End-to-end, deterministic multi-wave simulation of the canonical live Swarm.

Drives the REAL production functions in the order
``.github/workflows/orchid-swarm-controller.yml`` chains them, wave after wave,
against an in-memory GitHub (``tests/swarm_wave_github_fake.py``):

    lease reconcile  (scripts/oc_swarm_lease_reconcile.reconcile)        step "leases"
    snapshot         (FakeGitHub.snapshot, the "Build repository snapshot" shape)
    plan             (scripts/oc_swarm_controller.build_swarm_plan,
                      --provider-free-only because NO-API mode is blocked)  step "plan"
    claim            (scripts/oc_swarm_claim.claim_workers)                step "claim"
    worker           (oc_swarm_claim.verify_worker_claim ->
                      oc_swarm_provider_free_worker.build_receipt ->
                      oc_swarm_settlement.settle_worker)                   job "provider_free_workers"
    refill           (the refill job's ``if:`` and wave bound, re-stated)  job "refill"

Nothing is mocked inside those functions. The only substitutions are the
GitHub transport and a deterministic clock (the snapshot carries ``now`` so the
canonical scheduler's ``generated_at`` is reproducible; ranking never reads it).

Scenario (worker_slots=4, max_waves=4, the workflow's default wave bound):

    #101 Literature       provider-free, P1, writes literature
    #102 Atlas            provider-free, P1, writes atlas
    #103 Lexicon          provider-free, P1, OC-SWARM-DEPENDS-ON: #101
    #104 Calyx            provider-free, P0, but oc-owner-gate
    #105 Vision           provider-dependent (open-ended-code-authoring)
    #106 Research Station provider-free, P3, its worker dies every wave
    #107 Taxonomy A       provider-free, P2, writes taxonomy
    #108 Taxonomy B       provider-free, P2, writes taxonomy (lock contender)

Fixture only; never live execution evidence.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from scripts.oc_swarm_claim import claim_workers, verify_worker_claim
from scripts.oc_swarm_lease_reconcile import (
    MAX_AUTOMATIC_RECOVERIES,
    RECOVERY_PREFIX,
    reconcile,
)
from scripts.oc_swarm_provider_free_worker import build_receipt
from scripts.oc_swarm_settlement import settle_worker
from tests.swarm_wave_github_fake import FakeGitHub, ReconcileTransport

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_controller_wave_sim", ROOT / "scripts" / "oc_swarm_controller.py"
)
assert _SPEC is not None and _SPEC.loader is not None
controller = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(controller)

REPO = "owner/repo"
SLOTS = 4
MAX_WAVES = 4  # orchid-swarm-controller.yml default ``max_waves``
INTEGRATION_SHA = "0" * 40
RUN_BASE = 9000

LITERATURE, ATLAS, LEXICON, CALYX, VISION, RESEARCH, TAX_A, TAX_B = range(101, 109)
DYING = {RESEARCH}
NAMES = {LITERATURE: "Literature", ATLAS: "Atlas", LEXICON: "Lexicon", CALYX: "Calyx",
         VISION: "Vision", RESEARCH: "ResearchStation", TAX_A: "TaxonomyA", TAX_B: "TaxonomyB"}
NON_EXECUTABLE = {"oc-blocked", "oc-owner-gate", "oc-done", "oc-runtime-backoff", "oc-repair-backoff"}


def _body(*, writes: str, depends: str | None = None, provider_free: bool = True,
          extra: str = "") -> str:
    lines = []
    if provider_free:
        lines += ["OC-SWARM-PROVIDER-FREE: reconcile", "OC-SWARM-DISPOSITION: done"]
    else:
        lines += ["OC-SWARM-CAPABILITY: open-ended-code-authoring"]
    lines.append(f"OC-SWARM-WRITES: {writes}")
    if depends:
        lines.append(f"OC-SWARM-DEPENDS-ON: {depends}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def _issue(number, title, body, labels, minute):
    return {"number": number, "title": title, "body": body, "state": "OPEN",
            "labels": labels, "createdAt": f"2026-09-30T00:{minute:02d}:00Z"}


def scenario() -> list[dict]:
    return [
        _issue(LITERATURE, "Literature citation provenance reconcile",
               _body(writes="literature"), ["oc-queued", "oc-p1"], 1),
        _issue(ATLAS, "Atlas tour index reconcile",
               _body(writes="atlas"), ["oc-queued", "oc-p1"], 2),
        _issue(LEXICON, "Lexicon term index reconcile",
               _body(writes="lexicon", depends=f"#{LITERATURE}"), ["oc-queued", "oc-p1"], 3),
        _issue(CALYX, "Calyx activation reconcile",
               _body(writes="calyx"), ["oc-queued", "oc-owner-gate", "oc-p0"], 4),
        _issue(VISION, "Vision classifier implementation",
               _body(writes="images", provider_free=False), ["oc-queued", "oc-p1"], 5),
        _issue(RESEARCH, "Research Station brain sync reconcile",
               _body(writes="research-station"), ["oc-queued", "oc-p3"], 6),
        _issue(TAX_A, "Taxonomy synonym table reconcile",
               _body(writes="taxonomy"), ["oc-queued", "oc-p2"], 7),
        _issue(TAX_B, "Taxonomy accepted-name index reconcile",
               _body(writes="taxonomy"), ["oc-queued", "oc-p2"], 8),
    ]


# ---------------------------------------------------------------------------
# Independent oracle for the homeostasis invariant. Deliberately does not call
# the planner: it restates, from the snapshot alone, what "eligible, unlocked,
# ungated" means so the planner cannot grade its own homework.
# ---------------------------------------------------------------------------

def _names(issue):
    return {x if isinstance(x, str) else x["name"] for x in issue["labels"]}


def _writes(issue):
    match = re.search(r"^OC-SWARM-WRITES:\s*(.+)$", issue["body"], re.MULTILINE)
    return {part.strip() for part in match.group(1).split(",")} if match else set()


def _deps(issue):
    match = re.search(r"^OC-SWARM-DEPENDS-ON:\s*(.+)$", issue["body"], re.MULTILINE)
    return {int(x) for x in re.findall(r"#(\d+)", match.group(1))} if match else set()


def oracle_eligible(snapshot) -> set[int]:
    by_number = {i["number"]: i for i in snapshot["issues"]}
    running_writes = set()
    for issue in snapshot["issues"]:
        if "oc-running" in _names(issue):
            running_writes |= _writes(issue)
    eligible = set()
    for number, issue in by_number.items():
        labels = _names(issue)
        if issue["state"] != "OPEN" or "oc-queued" not in labels or "oc-running" in labels:
            continue
        if labels & NON_EXECUTABLE:
            continue
        if not re.search(r"^OC-SWARM-PROVIDER-FREE:\s*reconcile\s*$", issue["body"], re.MULTILINE):
            continue  # NO-API mode: only lane-executable work may run
        if any(dep not in by_number or not ({"oc-done"} & _names(by_number[dep])
                                            or by_number[dep]["state"] == "CLOSED")
               for dep in _deps(issue)):
            continue
        if _writes(issue) & running_writes:
            continue
        eligible.add(number)
    return eligible


# ---------------------------------------------------------------------------
# The simulation: one pass of the workflow per wave, refilled the way the
# workflow's ``refill`` job refills, bounded by ``max_waves``.
# ---------------------------------------------------------------------------

def _execute_worker(fake: FakeGitHub, worker: dict, *, run_id: int) -> str:
    """The provider_free_workers job for one matrix entry. Returns its outcome."""
    number = worker["issue_number"]
    comment_id = worker["lease_comment_id"]
    receipt = fake(["api", "--method", "GET", f"repos/{REPO}/issues/comments/{comment_id}"])
    issue = fake(["issue", "view", str(number), "--repo", REPO,
                  "--json", "number,title,body,state,labels"])
    verify_worker_claim(issue, receipt, repository=REPO, run_id=run_id, run_attempt=1,
                        comment_id=comment_id)
    if number in DYING:
        # Runner lost / cancelled: no result, no settlement, no failure() step.
        return "died"
    result = build_receipt(issue, lease_comment=receipt["body"], changed_files=[],
                           integration_sha=INTEGRATION_SHA)
    settle_worker(result=result, repository=REPO, issue_number=number, run_id=run_id,
                  run_attempt=1, comment_id=comment_id, call=fake)
    return result["disposition"]


def run_simulation() -> dict:
    fake = FakeGitHub(scenario(), repository=REPO)
    waves: list[dict] = []
    wave = 1
    while True:
        run_id = RUN_BASE + wave
        fake.advance(5)
        recon = reconcile(ReconcileTransport(fake), run_id=run_id, now=fake.now())
        snapshot = fake.snapshot()
        plan = controller.build_swarm_plan(snapshot, worker_slots=SLOTS, provider_free_only=True)
        fake.runs[run_id] = "in_progress"
        comments_before = sum(len(c) for c in fake.comments.values())
        handoff = claim_workers(plan, snapshot, repository=REPO, run_id=run_id,
                                run_attempt=1, call=fake)
        receipts_written = sum(len(c) for c in fake.comments.values()) - comments_before
        running_after_claim = sorted(n for n in fake.rows if "oc-running" in fake.labels(n))

        # A concurrent controller run (overlapping schedule pulse) replays the
        # same plan against the now-leased issues.
        before_dup = sum(len(c) for c in fake.comments.values())
        edits_dup = len(fake.edits)
        duplicate = claim_workers(plan, snapshot, repository=REPO, run_id=run_id + 500,
                                  run_attempt=1, call=fake)
        duplicate_writes = (sum(len(c) for c in fake.comments.values()) - before_dup,
                            len(fake.edits) - edits_dup)

        # A lease reconcile while this wave's run is still in progress must keep every lease.
        mid = reconcile(ReconcileTransport(fake), run_id=run_id + 900, now=fake.now(), dry_run=True)

        outcomes = {w["issue_number"]: _execute_worker(fake, w, run_id=run_id)
                    for w in handoff["provider_free_matrix"]["include"]}
        fake.runs[run_id] = "completed"

        refill = (handoff["launch_count"] > 0 and handoff["provider_free_launch_count"] > 0
                  and wave < MAX_WAVES)
        waves.append({
            "wave": wave, "run_id": run_id,
            "recovered": {d["issue_number"]: d["target"] for d in recon["recovered"]},
            "recon_errors": recon["errors"],
            "oracle_eligible": sorted(oracle_eligible(snapshot)),
            "plan": plan, "handoff": handoff, "duplicate": duplicate,
            "duplicate_writes": duplicate_writes, "receipts_written": receipts_written,
            "mid_recovered": [d["issue_number"] for d in mid["recovered"]],
            "running_after_claim": running_after_claim,
            "outcomes": outcomes, "refill": refill,
            "labels_after": {n: sorted(fake.labels(n)) for n in sorted(fake.rows)},
        })
        if not refill:
            break
        wave += 1
    return {"fake": fake, "waves": waves}


def trace(sim) -> str:
    lines = []
    for w in sim["waves"]:
        p = w["plan"]
        lines.append(
            f"W{w['wave']} run={w['run_id']} recovered={w['recovered']} "
            f"selected={p['selected_numbers']} launch={p['launch_count']} "
            f"confirmed={[x['issue_number'] for x in w['handoff']['confirmed']]} "
            f"dep_blocked={[x['issue_number'] for x in p['dependency_suppressed']]} "
            f"lock_blocked={[x['issue_number'] for x in p['resource_lock_suppressed']]} "
            f"refill_rec={p['refill_recommended']} outcomes={w['outcomes']} "
            f"oracle={w['oracle_eligible']} refill={w['refill']}"
        )
    final = sim["waves"][-1]["labels_after"]
    lines.append("final " + json.dumps({NAMES[n]: [x for x in v if not x.startswith("oc-p")]
                                         for n, v in final.items()}, sort_keys=True))
    return "\n".join(lines)


@pytest.fixture(scope="module")
def sim():
    return run_simulation()


def _selected(sim, wave):
    return set(sim["waves"][wave - 1]["plan"]["selected_numbers"])


def _confirmed(sim, wave):
    return {x["issue_number"] for x in sim["waves"][wave - 1]["handoff"]["confirmed"]}


def _ever_confirmed(sim):
    return set().union(*(_confirmed(sim, w["wave"]) for w in sim["waves"]))


# --------------------------------------------------------------------------- 1
def test_literature_and_atlas_are_leased_in_the_same_wave(sim):
    assert {LITERATURE, ATLAS} <= _confirmed(sim, 1), trace(sim)
    assert {LITERATURE, ATLAS} <= set(sim["waves"][0]["running_after_claim"]), trace(sim)


# --------------------------------------------------------------------------- 2
def test_owner_gated_calyx_is_never_claimed_and_never_holds_back_others(sim):
    assert CALYX not in _ever_confirmed(sim), trace(sim)
    assert all(CALYX not in w["plan"]["selected_numbers"] for w in sim["waves"]), trace(sim)
    gated = [x for x in sim["waves"][0]["plan"]["canonical_suppressed"] if x["number"] == CALYX]
    assert gated and gated[0]["reason"] == "oc-owner-gate", trace(sim)
    # P0 owner-gated work outranks everything yet wave 1 still filled every slot.
    assert sim["waves"][0]["plan"]["launch_count"] == SLOTS, trace(sim)
    assert {"oc-queued", "oc-owner-gate"} <= set(sim["waves"][-1]["labels_after"][CALYX]), trace(sim)


# --------------------------------------------------------------------------- 3
def test_provider_dependent_vision_stays_parked_while_provider_free_work_runs(sim):
    for w in sim["waves"]:
        assert VISION not in w["plan"]["selected_numbers"], trace(sim)
        assert w["plan"]["provider_launch_count"] == 0, trace(sim)
        assert w["handoff"]["provider_matrix"] == {"include": []}, trace(sim)
        # Not unstaffed: it genuinely needs a provider, which is the completion lane's.
        assert VISION not in w["plan"]["unstaffed_numbers"], trace(sim)
    assert sim["waves"][0]["plan"]["provider_free_launch_count"] > 0, trace(sim)
    final = set(sim["waves"][-1]["labels_after"][VISION])
    # Parked, not dead-lettered: still queued for a provider-enabled run.
    assert "oc-queued" in final and not final & {"oc-running", "oc-blocked", "oc-done"}, trace(sim)
    assert not sim["fake"].comments[VISION], trace(sim)


# --------------------------------------------------------------------------- 4
def test_lexicon_waits_for_literature_done_then_is_admitted_later(sim):
    w1 = sim["waves"][0]
    blocked = {x["issue_number"]: x for x in w1["plan"]["dependency_suppressed"]}
    assert LEXICON in blocked and blocked[LEXICON]["unsatisfied"] == [LITERATURE], trace(sim)
    assert LEXICON not in _confirmed(sim, 1), trace(sim)
    assert "oc-done" in w1["labels_after"][LITERATURE], trace(sim)
    first = min(w["wave"] for w in sim["waves"] if LEXICON in _confirmed(sim, w["wave"]))
    assert first == 2, trace(sim)
    assert sim["waves"][first - 1]["outcomes"][LEXICON] == "done", trace(sim)


# --------------------------------------------------------------------------- 5
def test_completion_replenishes_the_next_wave(sim):
    w1, w2 = sim["waves"][0], sim["waves"][1]
    assert w1["refill"] is True, trace(sim)  # the workflow's refill job dispatches wave 2
    # Wave 1 left dependency-blocked and capacity/lock-deferred work behind.
    assert w1["plan"]["refill_recommended"] is True, trace(sim)
    assert w1["plan"]["waiting_count"] == 2, trace(sim)
    assert {LEXICON, TAX_B, RESEARCH} == _confirmed(sim, 2), trace(sim)
    # Honest value: by wave 2's plan nothing ready is left waiting, so the hint is
    # False even though the dying worker will be requeued and need wave 3. The
    # workflow's refill job does not read this hint (it keys on launch counts),
    # so the lineage still continues.
    assert w2["plan"]["refill_recommended"] is False, trace(sim)
    assert w2["refill"] is True, trace(sim)


# --------------------------------------------------------------------------- 6
def test_second_claim_on_an_already_leased_issue_is_rejected(sim):
    for w in sim["waves"]:
        confirmed = _confirmed(sim, w["wave"])
        dup = w["duplicate"]
        assert dup["launch_count"] == 0 and dup["confirmed"] == [], trace(sim)
        assert {s["issue"] for s in dup["skipped"]} == confirmed, trace(sim)
        assert all(s["reason"] == "not_exclusively_queued" for s in dup["skipped"]), trace(sim)
        assert w["duplicate_writes"] == (0, 0), trace(sim)  # no receipt, no label edit
        assert w["receipts_written"] == len(confirmed), trace(sim)
        assert w["mid_recovered"] == [], trace(sim)  # in-progress leases are kept
    fake = sim["fake"]
    for comments in fake.comments.values():
        claims = [c for c in comments if "lease claimed" in c["body"]]
        lease_ids = [re.search(r'"lease_id":"([^"]+)"', c["body"]).group(1) for c in claims]
        assert len(lease_ids) == len(set(lease_ids)), trace(sim)
        # No lease was ever issued to the racing controller runs (run_id + 500).
        assert all(int(x.split(":")[1]) < RUN_BASE + 500 for x in lease_ids), trace(sim)


# --------------------------------------------------------------------------- 7
def test_dying_worker_is_requeued_at_most_max_recoveries_then_dead_lettered(sim):
    assert MAX_AUTOMATIC_RECOVERIES == 2
    targets = [w["recovered"][RESEARCH] for w in sim["waves"] if RESEARCH in w["recovered"]]
    assert targets == ["oc-queued"] * MAX_AUTOMATIC_RECOVERIES + ["oc-blocked"], trace(sim)
    claimed_in = [w["wave"] for w in sim["waves"] if RESEARCH in _confirmed(sim, w["wave"])]
    assert len(claimed_in) == MAX_AUTOMATIC_RECOVERIES + 1, trace(sim)
    recoveries = [c for c in sim["fake"].comments[RESEARCH] if c["body"].startswith(RECOVERY_PREFIX)]
    assert len(recoveries) == MAX_AUTOMATIC_RECOVERIES + 1, trace(sim)
    final = set(sim["waves"][-1]["labels_after"][RESEARCH])
    assert "oc-blocked" in final and not final & {"oc-queued", "oc-running"}, trace(sim)
    # The dead letter stays put: the blocked-work reconciler does not release it.
    last = sim["waves"][-1]["plan"]["blocked_reconciliation"]
    assert RESEARCH not in last["release_numbers"], trace(sim)
    # Its deaths never stopped the work that shared its waves.
    for wave in claimed_in:
        others = {n: o for n, o in sim["waves"][wave - 1]["outcomes"].items() if n != RESEARCH}
        assert all(o == "done" for o in others.values()), trace(sim)
    for number in (LITERATURE, ATLAS, LEXICON, TAX_A, TAX_B):
        assert "oc-done" in sim["waves"][-1]["labels_after"][number], trace(sim)


# --------------------------------------------------------------------------- 8
def test_lock_contended_pair_runs_one_per_wave(sim):
    w1 = sim["waves"][0]
    assert TAX_A in _confirmed(sim, 1) and TAX_B not in _confirmed(sim, 1), trace(sim)
    lock = [x for x in w1["plan"]["resource_lock_suppressed"] if x["issue_number"] == TAX_B]
    assert lock and lock[0]["blockers"] == [{"issue_number": TAX_A, "resources": ["taxonomy"]}], trace(sim)
    assert TAX_B in _confirmed(sim, 2), trace(sim)
    for w in sim["waves"]:
        assert not {TAX_A, TAX_B} <= set(w["running_after_claim"]), trace(sim)


# --------------------------------------------------------------------------- 9
def test_parallelism_never_exceeds_the_slot_cap(sim):
    for w in sim["waves"]:
        assert len(w["running_after_claim"]) <= SLOTS, trace(sim)
        p = w["plan"]
        assert p["active_worker_count"] + p["launch_count"] <= p["effective_worker_slots"] == SLOTS, trace(sim)
    assert sim["waves"][0]["plan"]["launch_count"] == SLOTS, trace(sim)  # the cap is reached


# -------------------------------------------------------------------------- 10
def test_no_wave_launches_nothing_while_eligible_work_exists(sim):
    for w in sim["waves"]:
        if w["oracle_eligible"]:
            assert w["plan"]["launch_count"] > 0, trace(sim)
            assert set(w["plan"]["selected_numbers"]) <= set(w["oracle_eligible"]), trace(sim)
        else:
            assert w["plan"]["launch_count"] == 0, trace(sim)


# ---------------------------------------------------------------------- final
def test_full_wave_trace(sim):
    """The whole lineage, compared at once; the message is the compact trace."""
    observed = [
        (w["wave"], sorted(_confirmed(sim, w["wave"])), w["recovered"], w["refill"])
        for w in sim["waves"]
    ]
    expected = [
        (1, [LITERATURE, ATLAS, RESEARCH, TAX_A], {}, True),
        (2, [LEXICON, RESEARCH, TAX_B], {RESEARCH: "oc-queued"}, True),
        (3, [RESEARCH], {RESEARCH: "oc-queued"}, True),
        (4, [], {RESEARCH: "oc-blocked"}, False),
    ]
    assert observed == expected, "\n" + trace(sim)
    assert all(not w["recon_errors"] and w["handoff"]["healthy"] for w in sim["waves"]), trace(sim)


def test_homeostasis_verdict_is_honest_every_wave(sim):
    """No wave claims healthy idle while unfinished work exists; gates are recorded precisely.

    Waves 1-3 execute. Wave 4 launches nothing, but the owner-gated Calyx issue and the
    provider-parked Vision issue are still unfinished, so the verdict must be ``gated``
    with both gates named and discovery requested -- never healthy idle.
    """
    verdicts = [w["plan"]["homeostasis"] for w in sim["waves"]]
    for verdict in verdicts:
        assert verdict["healthy_idle"] is False, trace(sim)
        assert verdict["gates"]["owner_gated"] == [CALYX], trace(sim)
        assert verdict["gates"]["provider_parked"] == [VISION], trace(sim)
    assert [v["reason"] for v in verdicts[:3]] == ["executing"] * 3, trace(sim)
    last = verdicts[-1]
    assert sim["waves"][-1]["plan"]["launch_count"] == 0, trace(sim)
    assert (last["status"], last["reason"]) == ("gated", "gated_only"), trace(sim)
    assert last["discovery_required"] is True, trace(sim)
    # The Lexicon dependency is recorded while it holds, and released once Literature is done.
    assert verdicts[0]["gates"]["dependency_blocked"] == [
        {"issue": LEXICON, "blocked_by": [LITERATURE], "roots": [LITERATURE], "gated": False}
    ], trace(sim)
    assert verdicts[1]["gates"]["dependency_blocked"] == [], trace(sim)


def test_scientific_gate_isolates_only_its_own_issue(monkeypatch):
    """A scientific/taxonomic gate parks exactly its issue; every other lane still completes."""
    import sys

    module = sys.modules[__name__]
    base = scenario()

    def gated_scenario():
        rows = [dict(row) for row in base]
        for row in rows:
            if row["number"] == ATLAS:
                row["labels"] = [*row["labels"], {"name": "oc-scientific-gate"}]
        return rows

    monkeypatch.setattr(module, "scenario", gated_scenario)
    gated = run_simulation()
    assert ATLAS not in _ever_confirmed(gated), trace(gated)
    assert all(w["plan"]["homeostasis"]["gates"]["scientific_gated"] == [ATLAS] for w in gated["waves"]), trace(gated)
    final = gated["waves"][-1]["labels_after"]
    for done in (LITERATURE, LEXICON, TAX_A, TAX_B):
        assert "oc-done" in final[done], trace(gated)
    assert not set(final[ATLAS]) & {"oc-running", "oc-done", "oc-blocked"}, trace(gated)
    assert gated["waves"][-1]["plan"]["homeostasis"]["healthy_idle"] is False, trace(gated)
