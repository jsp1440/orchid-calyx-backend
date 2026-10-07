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
    report = module_lanes.report_from_plan(snapshot, plan)
    assert plan == before
    [dispatch] = plan["coding_dispatch"]
    coding_selected = authorised and capability != "OC-SWARM-PROVIDER-FREE: missing-executor"
    assert plan["selected_numbers"] == ([1] if coding_selected else [2])
    assert report["evidence_category"] == "planning_and_issue_labels"
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
    failed_api = MockGitHub(issues)

    def fail_receipt(args, payload=None):
        if args[:3] == ["api", "--method", "POST"]:
            raise subprocess.TimeoutExpired("mock receipt write", 30)
        return failed_api(args, payload)

    failed_handoff = claim.claim_workers(
        plan, snapshot, repository="owner/repo", run_id=124, run_attempt=1, call=fail_receipt,
    )
    assert failed_handoff["healthy"] is False
    assert failed_handoff["confirmed"] == []
    assert failed_handoff["launch_count"] == 0
    assert failed_handoff["provider_launch_count"] == 0
    assert failed_handoff["provider_free_launch_count"] == 0
    assert failed_api.comments == []
    assert module_lanes.report_from_plan(snapshot, plan) == report
    claimed_snapshot = {"issues": list(api.issues.values()), "now": snapshot["now"]}
    after_claim = controller.build_swarm_plan(
        claimed_snapshot, worker_slots=1, coding_executor_available=authorised,
        provider_free_only=not authorised,
    )
    claimed_report = module_lanes.report_from_plan(claimed_snapshot, after_claim)
    selected_lane = "taxonomy" if coding_selected else "literature"
    assert claimed_report["lanes"][selected_lane]["running"] == plan["selected_numbers"]
    assert claimed_report["lanes"][selected_lane]["planned"] == []
    assert claimed_report["lanes"][selected_lane]["state"] == "executing"
    # Synthetic settlement labels are not worker completion/certification evidence.
    api.issues[plan["selected_numbers"][0]]["labels"] = ["oc-done", f"oc-lane:{selected_lane}"]
    api.issues[3] = {
        "number": 3, "state": "OPEN", "title": "Next independent literature fixture",
        "labels": ["oc-queued", "oc-lane:literature"],
        "body": "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-WRITES: literature",
    }
    continued_snapshot = {"issues": list(api.issues.values()), "now": snapshot["now"]}
    continued_plan = controller.build_swarm_plan(
        continued_snapshot, worker_slots=1, coding_executor_available=authorised,
        provider_free_only=not authorised,
    )
    continued_report = module_lanes.report_from_plan(continued_snapshot, continued_plan)
    assert continued_report["lanes"]["literature"]["state"] == "replenishable"
    assert continued_report["lanes"]["literature"]["next_mission"] in (2, 3)
    assert continued_plan["provider_launch_count"] == 0
    assert continued_plan["provider_free_launch_count"] == 1
