"""The autonomous execution lanes must survive an unrelated job failing.

Observed livelock, 2026-08-20. ``prepare`` selects backlog issues and labels
them ``oc-running``. The lanes then do the work and release the label. But the
lanes were gated only on ``needs.prepare.outputs.issueN != ''``.

An ``if:`` expression that never calls ``always()``, ``failure()`` or
``cancelled()`` gets an implicit ``success()`` ANDed in, and ``success()``
considers the *whole* needs chain, not just the direct parent. ``lane1`` needs
``prepare``, which needs ``planner``. So whenever ``planner`` failed - which it
did on every run, its Claude action erroring - GitHub skipped all three lanes
even though ``prepare`` itself had succeeded and had already marked the issues
``oc-running``.

The result was a perfect livelock rather than an outage, which is why it went
unnoticed: issues were claimed with nothing executing them, reclaimed 95 minutes
later as stale, then re-claimed within a minute by the next ``prepare``. Issue
#1030 cycled through that four times across five hours and produced no durable
pull request.

``prepare`` already guards itself with ``always()`` precisely so a planner
failure cannot stop it. These tests hold the lanes to the same contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(".github/workflows/orchid-continuous-completion.yml")
LANES = ("lane1", "lane2", "lane3")


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def test_every_lane_is_present(jobs):
    for lane in LANES:
        assert lane in jobs, f"{lane} is missing from the completion workflow"


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_not_skipped_when_an_unrelated_upstream_job_fails(jobs, lane):
    """Without always(), a failed planner silently disables the lane."""
    condition = jobs[lane]["if"]
    assert "always()" in condition, (
        f"{lane} must call always(); otherwise the implicit success() over its "
        "needs chain lets a failed planner skip it while prepare has already "
        "labelled the issue oc-running"
    )


@pytest.mark.parametrize("lane", LANES)
def test_lane_still_requires_prepare_to_have_succeeded(jobs, lane):
    """always() must not become 'run regardless'.

    The lane needs a real slot. Reading outputs from a prepare that failed would
    start a lane against an issue nobody selected.
    """
    condition = jobs[lane]["if"]
    assert "needs.prepare.result == 'success'" in condition, (
        f"{lane} must still require prepare to have succeeded"
    )


@pytest.mark.parametrize("lane,index", [(l, i) for i, l in enumerate(LANES, start=1)])
def test_lane_still_requires_a_non_empty_slot(jobs, lane, index):
    condition = jobs[lane]["if"]
    assert f"needs.prepare.outputs.issue{index} != ''" in condition, (
        f"{lane} must still refuse to run on an empty slot"
    )


def test_prepare_survives_a_planner_failure(jobs):
    """The behaviour the lanes are being aligned with."""
    condition = jobs["prepare"]["if"]
    assert "always()" in condition
    assert "needs.inventory.result == 'success'" in condition


def test_prepare_is_what_claims_issues_so_lanes_must_be_able_to_release_them(jobs):
    """Guards the invariant that made this a livelock rather than an outage.

    prepare applies oc-running. Only a lane removes it. If prepare can run while
    the lanes cannot, issues are claimed by something that will never release
    them.
    """
    prepare_run = " ".join(
        step.get("run", "") for step in jobs["prepare"]["steps"] if isinstance(step, dict)
    )
    assert "--add-label oc-running" in prepare_run, (
        "prepare is expected to claim issues; if that moved, this test's premise "
        "and the lane gating both need rechecking"
    )
