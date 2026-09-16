"""Stale ``oc-running`` lease reconciliation for the Swarm controller.

Fault-injecting fixtures only; nothing here is live execution evidence.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from scripts import oc_swarm_lease_reconcile as recon

REPO = "owner/repo"
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
BOT = {"login": "github-actions[bot]"}


def claim_comment(number=1, run_id=555, *, comment_id=900, created=None, login=BOT):
    claim = {"schema": "oc.swarm-claim.v1", "issue_number": number, "reads": [], "writes": ["x"],
             "dependencies": [], "lease_id": f"{REPO}:{run_id}:1:{number}",
             "material_fingerprint": "ab" * 8}
    body = ("[OC-SWARM-V4] Dependency/resource lease claimed: `"
            + json.dumps(claim, sort_keys=True, separators=(",", ":"))
            + f"`. packet={'ab' * 8}. Controller run: https://github.com/{REPO}/actions/runs/{run_id}.")
    return {"id": comment_id, "body": body, "user": login,
            "created_at": (created or NOW - timedelta(hours=2)).isoformat()}


def settlement_comment(created=None):
    return {"id": 901, "body": "[OC-AUTO] Lane delivered/updated integration PR #7, dispatched independent backend validation, and released its execution slot.",
            "user": BOT, "created_at": (created or NOW - timedelta(hours=1)).isoformat()}


def recovery_comment(comment_id):
    return {"id": comment_id, "body": recon.RECOVERY_PREFIX + '{"issue_number":1}`. Controller run: x.',
            "user": BOT, "created_at": (NOW - timedelta(days=1)).isoformat()}


def issue(number=1, labels=("oc-running", "oc-p4"), state="OPEN"):
    return {"number": number, "title": "Bounded work", "body": "", "state": state, "labels": list(labels)}


class Transport:
    """In-memory stand-in for the gh transport with fault injection."""

    def __init__(self, issues, *, comments=None, prs=None, labeled=None, runs=None):
        self.repository = REPO
        self.issues = {i["number"]: i for i in issues}
        self._comments = comments or {}
        self._prs = prs or []
        self._labeled = labeled or {}
        self._runs = runs or {}
        self.edits = []
        self.posted = []
        self.fail_edit = False
        self.leave_running_after_edit = False

    def running_issues(self):
        return [dict(i) for i in self.issues.values() if "oc-running" in i["labels"] and i["state"] == "OPEN"]

    def pull_requests(self):
        return list(self._prs)

    def comments(self, number):
        return list(self._comments.get(number, []))

    def labeled_at(self, number):
        return self._labeled.get(number)

    def run_status(self, run_id):
        return self._runs.get(run_id, "unknown")

    def issue(self, number):
        return dict(self.issues[number])

    def edit_labels(self, number, *, remove, add):
        if self.fail_edit:
            raise subprocess.TimeoutExpired("redacted", 60)
        self.edits.append((number, tuple(remove), tuple(add)))
        labels = [x for x in self.issues[number]["labels"] if x not in remove] + list(add)
        if self.leave_running_after_edit:
            labels.append("oc-running")
        self.issues[number]["labels"] = labels

    def comment(self, number, body):
        receipt = {"id": 1000 + len(self.posted), "body": body, "user": BOT}
        self.posted.append((number, body))
        return receipt


def run(transport, **kwargs):
    return recon.reconcile(transport, run_id=42, now=NOW, **kwargs)


def test_terminated_worker_run_releases_lease_and_requeues():
    t = Transport([issue()], comments={1: [claim_comment()]}, runs={555: "completed"})
    report = run(t)
    assert report["recovered_count"] == 1 and report["running_after"] == 0
    decision = report["recovered"][0]
    assert decision["reason"] == "worker_run_terminated_without_settlement"
    assert decision["target"] == "oc-queued" and decision["run_id"] == 555
    assert decision["lease_comment_id"] == 900
    assert t.edits == [(1, ("oc-running",), ("oc-queued",))]
    assert set(t.issues[1]["labels"]) == {"oc-queued", "oc-p4"}
    number, body = t.posted[0]
    assert number == 1 and body.startswith(recon.RECOVERY_PREFIX)
    payload = json.loads(body[len(recon.RECOVERY_PREFIX):body.index("`.")])
    assert payload["schema"] == recon.RECOVERY_SCHEMA
    assert payload["released_state"] == ["oc-p4", "oc-queued"]
    assert "actions/runs/42" in body


def test_missing_run_is_treated_as_terminated():
    t = Transport([issue()], comments={1: [claim_comment()]}, runs={555: "missing"})
    assert run(t)["recovered_count"] == 1


@pytest.mark.parametrize("status", ["in_progress", "queued", "unknown"])
def test_live_or_unreadable_run_keeps_the_slot_occupied(status):
    t = Transport([issue()], comments={1: [claim_comment()]}, runs={555: status})
    report = run(t)
    assert report["recovered_count"] == 0 and not t.edits and not t.posted
    assert report["kept"][0]["reason"] == "worker_run_active_or_unknown"


def test_settlement_after_claim_with_label_left_behind_is_recovered():
    t = Transport([issue()], comments={1: [claim_comment(), settlement_comment()]}, runs={555: "in_progress"})
    report = run(t)
    assert report["recovered"][0]["reason"] == "settled_without_label_release"


def test_settlement_before_claim_is_not_settlement_of_this_lease():
    old = settlement_comment(created=NOW - timedelta(hours=3))
    t = Transport([issue()], comments={1: [old, claim_comment()]}, runs={555: "in_progress"})
    assert run(t)["recovered_count"] == 0


def test_manual_lease_expires_after_horizon_and_merged_pr_moves_to_validating():
    prs = [{"number": 7, "state": "MERGED", "mergedAt": "2026-09-15T04:55:15Z", "body": "OC-AUTO-ISSUE: #1\n"}]
    t = Transport([issue(labels=("oc-running", "oc-queued", "oc-p1"))], prs=prs,
                  labeled={1: NOW - timedelta(days=3)})
    report = run(t)
    decision = report["recovered"][0]
    assert decision["reason"] == "manual_lease_expired"
    assert decision["target"] == "oc-validating" and decision["durable_pr"] == 7
    assert decision["lease_age_seconds"] == 3 * 24 * 3600
    assert set(t.issues[1]["labels"]) == {"oc-validating", "oc-p1"}


def test_manual_lease_within_horizon_or_unknown_age_is_kept():
    fresh = Transport([issue()], labeled={1: NOW - timedelta(hours=23)})
    assert run(fresh)["kept"][0]["reason"] == "manual_lease_within_horizon"
    unknown = Transport([issue()])
    assert run(unknown)["kept"][0]["reason"] == "manual_lease_age_unknown"
    assert not fresh.edits and not unknown.edits


def test_receipt_from_unauthenticated_user_is_ignored():
    t = Transport([issue()], comments={1: [claim_comment(login={"login": "someone"})]},
                  runs={555: "completed"})
    assert run(t)["kept"][0]["reason"] == "manual_lease_age_unknown"


def test_receipt_for_other_issue_or_repository_is_ignored():
    foreign = claim_comment(number=2)
    foreign["body"] = foreign["body"].replace('"issue_number":2', '"issue_number":1')
    t = Transport([issue()], comments={1: [foreign]}, runs={555: "completed"})
    assert run(t)["kept"][0]["reason"] == "manual_lease_age_unknown"


def test_automatic_recoveries_are_bounded_then_block():
    comments = [recovery_comment(1), recovery_comment(2), claim_comment()]
    t = Transport([issue()], comments={1: comments}, runs={555: "completed"})
    decision = run(t)["recovered"][0]
    assert decision["target"] == "oc-blocked"
    assert decision["recoveries_before"] == 2
    assert decision["reason"].endswith(":automatic_recoveries_exhausted")
    assert "oc-blocked" in t.issues[1]["labels"] and "oc-running" not in t.issues[1]["labels"]


def test_running_beside_parked_state_removes_only_the_stale_label():
    t = Transport([issue(labels=("oc-running", "oc-validating"))])
    decision = run(t)["recovered"][0]
    assert decision["reason"] == "running_label_beside_parked_state" and decision["target"] is None
    assert t.edits == [(1, ("oc-running",), ())]
    assert t.issues[1]["labels"] == ["oc-validating"]


def test_write_failure_is_recorded_without_receipt_or_retry():
    t = Transport([issue()], comments={1: [claim_comment()]}, runs={555: "completed"})
    t.fail_edit = True
    report = run(t)
    assert report["recovered_count"] == 0 and not t.posted
    assert report["errors"] == [{"issue": 1, "reason": "lease_reconcile_unconfirmed",
                                 "error_type": "TimeoutExpired"}]


def test_unconfirmed_release_never_writes_a_receipt():
    t = Transport([issue()], comments={1: [claim_comment()]}, runs={555: "completed"})
    t.leave_running_after_edit = True
    report = run(t)
    assert report["errors"][0]["error_type"] == "ValueError" and not t.posted


def test_dry_run_mutates_nothing():
    t = Transport([issue()], comments={1: [claim_comment()]}, runs={555: "completed"})
    report = run(t, dry_run=True)
    assert report["recovered_count"] == 1 and report["recovered"][0]["dry_run"] is True
    assert not t.edits and not t.posted


def test_one_failing_issue_does_not_stop_recovery_of_others():
    t = Transport([issue(1), issue(2)], comments={1: [claim_comment(1)], 2: [claim_comment(2, run_id=556)]},
                  runs={555: "completed", 556: "completed"})
    original = t.edit_labels

    def flaky(number, **kwargs):
        if number == 1:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502")
        return original(number, **kwargs)

    t.edit_labels = flaky
    report = run(t)
    assert report["recovered_count"] == 1 and report["recovered"][0]["issue_number"] == 2
    assert report["errors"][0]["issue"] == 1


def test_durable_pr_index_ignores_closed_unmerged_lineage():
    prs = [{"number": 3, "state": "CLOSED", "mergedAt": None, "body": "OC-AUTO-ISSUE: #1"},
           {"number": 4, "state": "OPEN", "mergedAt": None, "body": "OC-AUTO-ISSUE: #2"}]
    index = recon.durable_pr_index(prs)
    assert 1 not in index and index[2]["number"] == 4


def test_safety_receipt_declares_no_provider_or_time_based_release():
    report = run(Transport([]))
    assert report["safety"]["provider_calls"] is False
    assert report["safety"]["time_alone_releases_lease"] is False
    assert report["running_count"] == 0
