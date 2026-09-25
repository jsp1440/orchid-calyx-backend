"""Workflow contract for the parallel-executor repair of the Swarm v4 controller.

These assertions pin the hosted control path:
queue -> stale-lease reconcile -> plan -> claim (split by lane) -> matrix
workers -> settlement -> bounded refill on the same revision.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def _doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: dict, step_id: str) -> dict:
    return next(s for s in job["steps"] if s.get("id") == step_id)


def test_plan_reconciles_stale_leases_before_building_the_snapshot():
    plan = _doc()["jobs"]["plan"]
    names = [s.get("name") for s in plan["steps"]]
    reconcile = names.index("Reconcile stale execution leases")
    snapshot = names.index("Build repository snapshot")
    assert reconcile < snapshot
    step = _step(plan, "leases")
    assert "python3 -m scripts.oc_swarm_lease_reconcile" in step["run"]
    assert "--run-id \"$GITHUB_RUN_ID\"" in step["run"]
    assert plan["outputs"]["recovered_count"] == "${{ steps.leases.outputs.recovered_count }}"


def test_controller_pins_trusted_code_to_the_event_revision():
    jobs = _doc()["jobs"]
    for job in ("plan", "provider_free_workers"):
        checkout = next(s for s in jobs[job]["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
        assert checkout["with"]["ref"] == "${{ github.sha }}"


def test_provider_free_and_paid_lanes_are_split_by_confirmed_claim_matrices():
    jobs = _doc()["jobs"]
    plan = jobs["plan"]
    assert plan["outputs"]["provider_free_matrix"] == "${{ steps.claim.outputs.provider_free_matrix }}"
    assert plan["outputs"]["provider_matrix"] == "${{ steps.claim.outputs.provider_matrix }}"
    assert plan["outputs"]["provider_free_launch_count"] == "${{ steps.claim.outputs.provider_free_launch_count }}"
    assert plan["outputs"]["provider_launch_count"] == "${{ steps.claim.outputs.provider_launch_count }}"

    workers = jobs["workers"]
    assert workers["strategy"]["matrix"] == "${{ fromJSON(needs.plan.outputs.provider_matrix) }}"
    assert "needs.plan.outputs.provider_launch_count != '0'" in workers["if"]
    assert "needs.plan.outputs.provider_blocked == 'false'" in workers["if"]

    free = jobs["provider_free_workers"]
    assert free["strategy"]["matrix"] == "${{ fromJSON(needs.plan.outputs.provider_free_matrix) }}"
    assert free["if"] == "needs.plan.outputs.provider_free_launch_count != '0'"
    assert "provider_blocked" not in free["if"]
    assert free["strategy"]["fail-fast"] is False  # one failing lane never stops siblings


def test_provider_free_lane_writes_only_through_the_fenced_edit_lane():
    # Was `contents: read`. The edit lane (#1606/#1610) pushes one
    # oc/discovered-<fingerprint> branch and opens a draft PR, so this job holds
    # contents/pull-requests write -- and nothing else does it: the job's own
    # shell never pushes, opens or merges a PR, and a pre-push fence precedes
    # every step that could push.
    free = _doc()["jobs"]["provider_free_workers"]
    # `actions: write` dispatches exact-head validation for the lane's PR: one
    # opened with GITHUB_TOKEN starts no pull_request workflow of its own.
    assert free["permissions"] == {
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
        "actions": "write",
    }
    run_text = "\n".join(str(s.get("run", "")) for s in free["steps"])
    assert "git push" not in run_text and "gh pr create" not in run_text
    assert "gh pr merge" not in run_text
    dispatched = re.findall(r"gh workflow run (\S+)", run_text)
    assert dispatched == ["orchid-autonomous-validation.yml"]
    names = [s.get("name", "") for s in free["steps"]]
    fence = names.index("Fence pushes to oc/discovered-* branches")
    assert fence < names.index("Execute deterministic provider-free work")
    assert "ANTHROPIC_API_KEY" not in WORKFLOW.read_text(encoding="utf-8").split("provider_free_workers:")[1].split("refill:")[0]


def test_failed_provider_free_lane_releases_lease_with_exact_evidence():
    free = _doc()["jobs"]["provider_free_workers"]
    step = next(s for s in free["steps"] if s.get("name", "").startswith("Fail closed and release lease"))
    assert step["if"] == "failure() && steps.lease.outputs.execute == 'true'"
    assert "provider-free-result.json" in step["run"]
    assert "--remove-label oc-running" in step["run"]
    assert "--add-label oc-blocked" in step["run"]
    assert "Worker evidence:" in step["run"]


def test_refill_follows_completion_for_provider_free_waves_and_stays_on_the_same_revision():
    refill = _doc()["jobs"]["refill"]
    condition = refill["if"]
    assert "needs.plan.outputs.provider_free_launch_count != '0'" in condition
    assert "needs.plan.outputs.provider_blocked == 'true' && vars.OC_GOVERNOR_AUTO_REFILL == 'true'" in condition
    assert "needs.plan.outputs.launch_count != '0'" in condition
    # Hosted wave 35067378022: one simulated-failure lane made the matrix job
    # result 'failure' and the old condition suppressed refill of unrelated work.
    assert "needs.provider_free_workers.result != 'failure'" not in condition
    assert "needs.provider_free_workers.result != 'cancelled'" in condition
    run = refill["steps"][0]["run"]
    assert 'refill_ref="$INTEGRATION_BRANCH"' in run
    assert 'refill_ref="$GITHUB_REF_NAME"' in run
    assert '--ref "$refill_ref"' in run
    assert "current >= maximum" in run  # bounded waves


def test_summary_reports_lane_counts_and_recoveries():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "provider_free_launch_count:" in text
    assert "provider_launch_count:" in text
    assert "stale leases recovered:" in text
