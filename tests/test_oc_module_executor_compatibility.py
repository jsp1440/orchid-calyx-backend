"""Opt-in, mocked compatibility with unmerged #1767, not lifecycle evidence.

Fetch #1767's pinned head read-only, then set OC_MODULE_COMPAT_HEAD to that SHA.
The test executes Git objects in memory; it never writes another branch's code
into the checkout or performs GitHub/provider calls.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

from app import autonomy
from app.autonomy import module_lanes

EXECUTOR_HEAD = "e3773086926666cdabf3111bbf57a7dc1ba3b1ed"
ROOT = Path(__file__).resolve().parents[1]


def _git_module(name, path, monkeypatch):
    source = subprocess.run(
        ["git", "show", f"{EXECUTOR_HEAD}:{path}"], cwd=ROOT,
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102 - pinned read-only Git source
    return module


class MockGitHub:
    def __init__(self, issues):
        self.issues = {row["number"]: deepcopy(row) for row in issues}
        self.comments = []

    def __call__(self, args, payload=None):
        if args[:2] == ["issue", "view"]:
            return deepcopy(self.issues[int(args[2])])
        if args[:2] == ["issue", "edit"]:
            issue = self.issues[int(args[2])]
            issue["labels"] = [n for n in issue["labels"] if n != "oc-queued"] + ["oc-running"]
            return None
        assert args[:3] == ["api", "--method", "POST"]
        receipt = {"id": len(self.comments) + 100, "body": payload["body"],
                   "user": {"login": "github-actions[bot]"}}
        self.comments.append(receipt)
        return receipt


@pytest.mark.parametrize("authorised", [False, True])
@pytest.mark.parametrize("capability", [
    "OC-SWARM-PROVIDER-FREE: missing-executor",
    "OC-SWARM-CAPABILITY: taxonomy-resolution",
    "OC-SWARM-PROVIDER-FREE: missing-executor\nOC-SWARM-CAPABILITY: open-ended-code-authoring",
])
def test_exact_executor_plan_claim_and_module_report(monkeypatch, authorised, capability):
    requested = os.environ.get("OC_MODULE_COMPAT_HEAD")
    if requested is None:
        pytest.skip("opt-in unmerged #1767 Git-object compatibility; not runtime evidence")
    assert requested == EXECUTOR_HEAD, "compatibility evidence must use the pinned exact head"
    subprocess.run(
        ["git", "diff", "--quiet", EXECUTOR_HEAD, "HEAD", "--",
         "app/provider_reservoir", "runtime/swarm/work_packet.py",
         "scripts/oc_portfolio_scheduler.py", "scripts/oc_swarm_resource_locks.py",
         "scripts/oc_swarm_dependency_graph.py", "scripts/oc_blocked_reconcile.py",
         "scripts/oc_budget_blocker.py", "scripts/oc_budget_denial_route.py",
         "scripts/oc_health_contract.py"],
        cwd=ROOT, check=True, timeout=30,
    )
    coding = _git_module("app.autonomy.coding_executor", "app/autonomy/coding_executor.py", monkeypatch)
    monkeypatch.setattr(autonomy, "coding_executor", coding, raising=False)
    controller = _git_module("module_compat_controller", "scripts/oc_swarm_controller.py", monkeypatch)
    claim = _git_module("module_compat_claim", "scripts/oc_swarm_claim.py", monkeypatch)
    issues = [
        {"number": 1, "state": "OPEN", "title": "Taxonomy work",
         "labels": ["oc-queued", "oc-p0", "oc-lane:taxonomy"],
         "body": capability + "\nOC-SWARM-WRITES: shared"},
        {"number": 2, "state": "OPEN", "title": "Literature work",
         "labels": ["oc-queued", "oc-p4", "oc-lane:literature"],
         "body": "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-WRITES: shared"},
    ]
    snapshot = {"issues": issues, "now": "2026-10-01T00:00:00Z"}
    plan = controller.build_swarm_plan(
        snapshot, worker_slots=1, coding_executor_available=authorised,
        provider_free_only=not authorised,
    )
    before = deepcopy(plan)
    report = module_lanes.lane_report(
        issues, capability_gap=plan["unstaffed_numbers"],
        lane_refusals=plan["lane_refusals"], coding_dispatch=plan["coding_dispatch"],
    )
    assert plan == before
    [dispatch] = plan["coding_dispatch"]
    coding_selected = authorised and capability != "OC-SWARM-PROVIDER-FREE: missing-executor"
    assert plan["selected_numbers"] == ([1] if coding_selected else [2])
    taxonomy = report["lanes"]["taxonomy"]
    if coding_selected:
        assert taxonomy["state"] == "replenishable"
        assert taxonomy["running"] == []
    else:
        assert taxonomy["state"] == (
            "capability_gap" if dispatch["state"] == "capability_gap" else "gated"
        )
        assert taxonomy["next_mission"] is None
        assert taxonomy["refusal_reasons"] == [{"issue": 1, "reason": dispatch["gate"]}]
        assert report["lanes"]["literature"]["next_mission"] == 2
    assert plan["homeostasis"]["healthy_idle"] is False
    api = MockGitHub(issues)
    handoff = claim.claim_workers(
        plan, snapshot, repository="owner/repo", run_id=123, run_attempt=1, call=api,
    )
    assert handoff["healthy"] is True
    assert handoff["provider_launch_count"] == plan["provider_launch_count"] == int(coding_selected)
    assert handoff["provider_free_launch_count"] == int(not coding_selected)
    assert len(api.comments) == handoff["launch_count"] == 1
    assert dispatch["provider_called"] is False
