"""R1 composition proof: a multi-cycle control loop over the real components.

What is real here: ``build_swarm_plan`` (planning, gating, homeostasis), the
coding-executor lifecycle and its checksum chain, the module-lane report, and
the Calyx advisory pipeline. What is simulated, and labelled so in every
receipt: the executors themselves (no worker runs, no provider is called, no
code is written by anything but this test). This proves the pieces compose and
that the loop never mistakes a gate for idleness. It is NOT live autonomy
evidence; the live proof needs an authorised coding executor and real runs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.autonomy import coding_executor as ce
from app.autonomy import module_lanes as ml
from app.calyx_advisory import pipeline as calyx_pipeline

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_controller_proof", ROOT / "scripts" / "oc_swarm_controller.py"
)
swarm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(swarm)

FIXTURE = ROOT / "tests" / "fixtures" / "calyx_advisory" / "contested_pollination.json"
EXEC = "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-WRITES: {w}"
CODE = "OC-SWARM-CAPABILITY: taxonomy-resolution\nOC-SWARM-WRITES: {w}"
BRANCH = "oc-autonomous-integration"


class World:
    """In-memory issue store plus the receipts the loop leaves behind."""

    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.next_number = 100
        self.receipts: list[dict] = []
        self.missions: dict[int, dict] = {}
        self.known_fingerprints: frozenset[str] = frozenset()

    def file(self, lane, body, *labels, title="bounded work"):
        number = self.next_number
        self.next_number += 1
        self.issues[number] = {
            "number": number, "title": title, "state": "OPEN", "body": body,
            "labels": [*labels, f"oc-lane:{lane}"], "createdAt": "2026-09-01T00:00:00Z",
        }
        return number

    def snapshot(self):
        return {"issues": [dict(i) for i in self.issues.values()], "now": "2026-10-01T00:00:00Z"}

    def finish(self, number):
        issue = self.issues[number]
        issue["labels"] = [lb for lb in issue["labels"] if lb != "oc-queued"] + ["oc-done"]
        issue["state"] = "CLOSED"


def _run_coding_mission(world, number, plan):
    """Simulated coding executor: drives every lifecycle state with checksummed evidence."""
    m = ce.new_mission(number, base_branch=BRANCH, maker="coding-executor-sim")
    head = f"sim{number:06d}"
    for state, ev in [
        ("leased", {"lease_id": f"lease-{number}"}),
        ("executing", {"run_id": f"sim-run-{number}"}),
        ("implementation_complete", {"head_sha": head, "pull_request": 9000 + number}),
        ("testing", {"head_sha": head}),
        ("certification", {"head_sha": head, "checks_passed": True}),
        ("integration_ready", {"head_sha": head, "checker": "checker-sim", "target_branch": BRANCH}),
        ("integrated", {"merge_commit": f"merge{number}", "target_branch": BRANCH}),
    ]:
        m = ce.advance(m, state, **ev)
    world.finish(number)
    return m


def _cycle(world, n, *, coding_available):
    plan = swarm.build_swarm_plan(
        world.snapshot(), worker_slots=3, coding_executor_available=coding_available
    )
    launched = list(plan["selected_numbers"])
    for number in launched:
        issue = world.issues[number]
        if swarm.is_lane_executable(issue):
            world.finish(number)  # simulated deterministic worker
            world.missions[number] = {"kind": "deterministic", "state": "done"}
        else:
            world.missions[number] = _run_coding_mission(world, number, plan)
    lanes = ml.lane_report(
        world.snapshot()["issues"],
        capability_gap=swarm.unstaffed_numbers(world.snapshot()),
    )
    receipt = {
        "cycle": n,
        "evidence_class": "simulation",
        "launched": launched,
        "homeostasis": plan["homeostasis"]["reason"],
        "healthy_idle": plan["homeostasis"]["healthy_idle"],
        "coding_states": {r["issue_number"]: r["state"] for r in plan["coding_dispatch"]},
        "lane_summary": lanes["summary"],
    }
    world.receipts.append(receipt)
    return plan, receipt


def test_ten_cycle_loop_composes_discovery_dispatch_lifecycle_calyx_and_replenishment():
    world = World()
    lit = world.file("literature", EXEC.format(w="lit"), "oc-queued", title="Literature DOI work")
    code = world.file("infrastructure-federation", CODE.format(w="infra"), "oc-queued",
                      title="Controller code authoring")
    owner = world.file("atlas-geography-environment", EXEC.format(w="atlas"), "oc-queued", "oc-owner-gate")
    sci = world.file("taxonomy", EXEC.format(w="tax"), "oc-queued", "oc-scientific-gate")

    # Cycles 1-3: providers not authorised. Deterministic lane works; code
    # authoring is named provider_blocked; human-gated lanes never launch.
    for n in (1, 2, 3):
        plan, receipt = _cycle(world, n, coding_available=False)
        assert owner not in receipt["launched"] and sci not in receipt["launched"]
        if n == 1:
            assert receipt["launched"] == [lit]
        assert receipt["coding_states"][code] == "provider_blocked"
        assert receipt["healthy_idle"] is False
        assert plan["homeostasis"]["gates"]["coding_executor_blocked"] == [code]
    assert world.issues[lit]["state"] == "CLOSED" and world.issues[code]["state"] == "OPEN"

    # Cycle 4: the owner authorises providers (simulated). The same work now
    # dispatches through the coding-executor path and completes with a receipt chain.
    _, receipt = _cycle(world, 4, coding_available=True)
    assert receipt["launched"] == [code]
    mission = world.missions[code]
    assert ce.verify_chain(mission)
    assert [e["to"] for e in mission["history"]][-1] == "integrated"
    assert mission["maker"] != mission["history"][-2]["evidence"]["checker"]

    # Cycle 5: replenishment. Calyx evaluates the contested-pollination artifact
    # and its bounded candidates are filed as new work in their routed lanes.
    artifact = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = calyx_pipeline.run(artifact, known_fingerprints=world.known_fingerprints)
    assert result["receipt"]["passed"] is True
    filed = [
        world.file(c["target_module"], CODE.format(w=f"calyx-{c['fingerprint']}"), "oc-queued",
                   title=f"Calyx {c['finding_kind']}")
        for c in result["candidates"]
    ]
    world.known_fingerprints = frozenset(result["receipt"]["candidate_fingerprints"])
    assert len(filed) == len(result["candidates"]) >= 4
    _, receipt = _cycle(world, 5, coding_available=True)
    assert len(receipt["launched"]) == 3  # bounded by slots; the rest wait for later cycles

    # Cycles 6-10: remaining replenished work drains; nothing launched is gated.
    for n in range(6, 11):
        _, receipt = _cycle(world, n, coding_available=True)
        assert owner not in receipt["launched"] and sci not in receipt["launched"]
    # Once the replenished work is drained the loop must say so honestly: an
    # empty queue is "replenish" (discovery required), never healthy idle. Only
    # cycles 1, 4, 5 and 6 did work; the proof does not pretend all ten did.
    productive = [r["cycle"] for r in world.receipts if r["launched"]]
    assert productive == [1, 4, 5, 6]
    for r in world.receipts[6:]:
        assert r["homeostasis"] == "queue_empty" and r["healthy_idle"] is False

    # A second Calyx pass proposes nothing new: idempotent, no duplicate work.
    again = calyx_pipeline.run(artifact, known_fingerprints=world.known_fingerprints)
    assert again["candidates"] == []

    assert len(world.receipts) == 10
    assert all(r["evidence_class"] == "simulation" for r in world.receipts)
    # Real work was launched in at least two independent lanes over the run.
    lanes_that_worked = {
        ml.assign_lane(world.issues[n])[0] for n in world.missions
    }
    assert {"literature", "infrastructure-federation"} <= lanes_that_worked
    assert len(lanes_that_worked) >= 3
    # The end state is honest: only human-gated work remains, and the controller
    # says gated, not healthy idle (no discovery evidence was attached).
    final = swarm.build_swarm_plan(world.snapshot(), worker_slots=3, coding_executor_available=True)
    assert final["launch_count"] == 0
    assert final["homeostasis"]["reason"] == "gated_only"
    assert final["homeostasis"]["healthy_idle"] is False
    assert set(final["homeostasis"]["gates"]["owner_gated"]) == {owner}
    assert set(final["homeostasis"]["gates"]["scientific_gated"]) == {sci}
