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

    def __init__(self, issues, *, comments=None, prs=None, labeled=None, runs=None, conclusions=None):
        self.repository = REPO
        self.issues = {i["number"]: i for i in issues}
        self._comments = comments or {}
        self._prs = prs or []
        self._labeled = labeled or {}
        self._runs = runs or {}
        self._conclusions = conclusions or {}
        self.edits = []
        self.posted = []
        self.closed = []
        self.fail_edit = False
        self.leave_running_after_edit = False

    def running_issues(self):
        return [dict(i) for i in self.issues.values() if "oc-running" in i["labels"] and i["state"] == "OPEN"]

    def validating_issues(self):
        return [dict(i) for i in self.issues.values() if "oc-validating" in i["labels"] and i["state"] == "OPEN"]

    def parked_issues(self):
        parked = {"oc-blocked", "oc-runtime-backoff", "oc-repair-backoff"}
        return [dict(i) for i in self.issues.values() if parked & set(i["labels"]) and i["state"] == "OPEN"]

    def run_conclusion(self, run_id):
        return self._conclusions.get(run_id, "unknown")

    def close_pull_request(self, number, body):
        self.closed.append((number, body))

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


def test_claim_for_other_issue_fails_closed_without_releasing_lease():
    foreign = claim_comment(number=2)
    t = Transport([issue()], comments={1: [foreign]}, runs={555: "completed"})
    report = run(t)
    assert report["recovered_count"] == 0 and report["running_after"] == 1
    assert report["errors"] == [
        {
            "issue": 1,
            "reason": "lease_reconcile_unconfirmed",
            "error_type": "ValueError",
        }
    ]
    assert not t.edits and not t.posted


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


def test_running_beside_scientific_gate_is_parked_not_requeued():
    t = Transport([issue(labels=("oc-running", "oc-scientific-gate"))])
    decision = run(t)["recovered"][0]
    assert decision["reason"] == "running_label_beside_parked_state" and decision["target"] is None
    assert t.issues[1]["labels"] == ["oc-scientific-gate"]


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


# --- #1938: an oc-validating issue whose worker run did not succeed ---------

OPEN_PR = {"number": 7, "state": "OPEN", "mergedAt": None, "body": "OC-AUTO-ISSUE: #1\n"}


def stranded(conclusion="cancelled", *, prs=(OPEN_PR,), comments=None, status="completed",
             labels=("oc-validating", "oc-model-cheap")):
    return Transport(
        [issue(labels=labels)],
        comments={1: comments if comments is not None else [claim_comment()]},
        prs=list(prs),
        runs={555: status},
        conclusions={555: conclusion},
    )


@pytest.mark.parametrize("conclusion", ["cancelled", "failure", "timed_out", "startup_failure"])
def test_validating_issue_with_unsuccessful_worker_run_is_requeued(conclusion):
    t = stranded(conclusion)
    report = run(t)
    assert report["stranded_recovered_count"] == 1
    decision = report["stranded_recovered"][0]
    assert decision["reason"] == recon.STRANDED_REASON
    assert decision["target"] == "oc-queued" and decision["stranded_pr"] == 7
    assert decision["run_id"] == 555 and decision["lease_comment_id"] == 900
    assert decision["run_conclusion"] == conclusion
    assert t.edits == [(1, ("oc-validating",), ("oc-queued",))]
    assert set(t.issues[1]["labels"]) == {"oc-queued", "oc-model-cheap"}
    number, body = t.posted[-1]
    payload = json.loads(body[len(recon.RECOVERY_PREFIX):body.index("`.")])
    assert number == 1 and payload["schema"] == recon.RECOVERY_SCHEMA
    assert payload["reason"] == recon.STRANDED_REASON and payload["stranded_pr"] == 7
    assert payload["released_state"] == ["oc-model-cheap", "oc-queued"]


def test_the_stranded_pr_is_never_touched():
    """The plan job has read-only pull-request access; only the issue is written."""
    t = stranded()
    run(t)
    assert not t.closed
    assert [number for number, _ in t.posted] == [1]


@pytest.mark.parametrize("conclusion", ["success", "unknown", "neutral", "skipped", None])
def test_successful_or_unknown_worker_run_is_left_alone(conclusion):
    t = stranded(conclusion)
    report = run(t)
    assert report["stranded_recovered_count"] == 0
    assert not t.edits and not t.posted


@pytest.mark.parametrize("status", ["in_progress", "queued", "unknown", "missing"])
def test_worker_run_not_completed_is_left_alone(status):
    t = stranded(status=status)
    assert run(t)["stranded_recovered_count"] == 0 and not t.edits


def test_merged_integration_pr_is_never_requeued():
    merged = {**OPEN_PR, "state": "MERGED", "mergedAt": "2026-09-16T10:00:00Z"}
    t = stranded(prs=(merged,))
    assert run(t)["stranded_recovered_count"] == 0 and not t.edits


@pytest.mark.parametrize(
    "extra",
    ["oc-owner-gate", "oc-scientific-gate", "oc-blocked", "oc-repair", "oc-queued",
     "oc-done", "oc-runtime-backoff", "oc-repair-backoff"],
)
def test_validating_beside_any_other_state_or_gate_is_left_alone(extra):
    t = stranded(labels=("oc-validating", extra))
    report = run(t)
    assert report["stranded_recovered_count"] == 0 and not t.edits and not t.posted


def test_validating_without_an_authenticated_claim_is_left_alone():
    t = stranded(comments=[])
    assert run(t)["stranded_recovered_count"] == 0 and not t.edits
    forged = stranded(comments=[claim_comment(login={"login": "someone"})])
    assert run(forged)["stranded_recovered_count"] == 0 and not forged.edits


def test_no_open_pr_still_requeues():
    t = stranded(prs=())
    decision = run(t)["stranded_recovered"][0]
    assert decision["stranded_pr"] is None
    assert set(t.issues[1]["labels"]) == {"oc-queued", "oc-model-cheap"}


def test_a_requeued_issue_is_not_recovered_again_on_the_next_pass():
    t = stranded()
    assert run(t)["stranded_recovered_count"] == 1
    assert run(t)["stranded_recovered_count"] == 0
    assert len(t.posted) == 1


def test_stranded_recoveries_share_the_bounded_budget():
    comments = [recovery_comment(1), recovery_comment(2), claim_comment()]
    t = stranded(comments=comments)
    decision = run(t)["stranded_recovered"][0]
    assert decision["target"] == "oc-blocked"
    assert decision["reason"] == f"{recon.STRANDED_REASON}:automatic_recoveries_exhausted"
    assert set(t.issues[1]["labels"]) == {"oc-blocked", "oc-model-cheap"}


def test_label_write_failure_writes_no_receipt():
    t = stranded()
    t.fail_edit = True
    report = run(t)
    assert report["stranded_recovered_count"] == 0 and not t.posted
    assert report["errors"] == [
        {"issue": 1, "reason": "stranded_validation_unconfirmed", "error_type": "TimeoutExpired"}
    ]


def test_dry_run_relabels_nothing():
    t = stranded()
    report = run(t, dry_run=True)
    assert report["stranded_recovered"][0]["dry_run"] is True
    assert not t.edits and not t.posted


def test_running_issues_are_not_also_treated_as_stranded():
    t = Transport(
        [issue(labels=("oc-running", "oc-validating"))],
        comments={1: [claim_comment()]},
        prs=[OPEN_PR],
        runs={555: "completed"},
        conclusions={555: "cancelled"},
    )
    report = run(t)
    assert report["recovered"][0]["reason"] == "running_label_beside_parked_state"
    assert report["stranded_recovered_count"] == 0


def test_the_acceptance_report_counts_the_stranded_recovery_reason():
    from scripts import oc_engineering_acceptance_report as acceptance

    assert recon.STRANDED_REASON in acceptance.RECOVER_REASONS


# --- Leases on parked issues (#1396) ------------------------------------------


def denied_release(lease_comment_id, number=1, run_id=556, *, comment_id=910):
    """The receipt that released #1396's second claim (comment 5649484252)."""
    release = {"issue_number": number, "lease_comment_id": lease_comment_id,
               "lease_id": f"{REPO}:{run_id}:1:{number}", "material_fingerprint": "ab" * 8,
               "provider_called": False, "reason": "BLOCKED_MONTHLY_BUDGET_EXCEEDED",
               "schema": "oc.swarm-denied-release.v1", "state": "oc-blocked"}
    return {"id": comment_id, "user": BOT, "created_at": (NOW - timedelta(minutes=50)).isoformat(),
            "body": "[OC-SWARM-V4] Provider admission denied; execution lease released: `"
            + json.dumps(release, sort_keys=True) + "`."}


def issue_1396_shape(**runs):
    """Two runs claimed one packet 15s apart; only the second was released."""
    first = claim_comment(run_id=555, comment_id=900, created=NOW - timedelta(hours=1))
    second = claim_comment(run_id=556, comment_id=905,
                           created=NOW - timedelta(hours=1) + timedelta(seconds=15))
    return Transport([issue(labels=("oc-blocked", "oc-p1", "oc-repair"))],
                     comments={1: [first, second, denied_release(905)]},
                     runs={555: "completed", 556: "completed", **runs})


def receipt_payload(body):
    return json.loads(body[len(recon.RECOVERY_PREFIX):body.index("`.")])


def test_an_unreleased_lease_on_a_parked_issue_is_receipted_without_label_edits():
    t = issue_1396_shape()
    report = run(t)
    assert report["parked_lease_recovered_count"] == 1
    decision = report["parked_lease_recovered"][0]
    assert decision["reason"] == recon.PARKED_LEASE_REASON
    assert decision["lease_comment_id"] == 900 and decision["run_id"] == 555
    assert decision["target"] is None
    assert t.edits == []
    (number, body), = t.posted
    payload = receipt_payload(body)
    assert number == 1 and payload["lease_id"] == f"{REPO}:555:1:1"
    assert payload["released_state"] == ["oc-blocked", "oc-p1", "oc-repair"]
    assert "actions/runs/42" in body


def test_the_receipt_settles_the_lease_so_the_next_wave_writes_nothing():
    t = issue_1396_shape()
    run(t)
    _, body = t.posted[0]
    t._comments[1].append({"id": 1000, "body": body, "user": BOT,
                           "created_at": NOW.isoformat()})
    t.posted.clear()
    assert run(t)["parked_lease_recovered_count"] == 0 and t.posted == []


def test_the_receipt_does_not_spend_the_requeue_budget():
    t = issue_1396_shape()
    run(t)
    _, body = t.posted[0]
    comments = [{"id": 1000, "body": body, "user": BOT, "created_at": NOW.isoformat()}]
    assert recon._recovery_count(comments) == 0
    assert recon._recovery_count([recovery_comment(77)]) == 1


@pytest.mark.parametrize("status", ["in_progress", "queued", "unknown"])
def test_a_live_or_unreadable_run_keeps_every_lease_on_the_issue(status):
    t = issue_1396_shape(**{"555": None})
    t._runs[555] = status
    report = run(t)
    assert report["parked_lease_recovered_count"] == 0 and t.posted == []


def test_one_live_run_holds_back_an_otherwise_terminated_lease():
    t = issue_1396_shape()
    t._comments[1].append(claim_comment(run_id=557, comment_id=920, created=NOW - timedelta(minutes=5)))
    t._runs[557] = "in_progress"
    assert run(t)["parked_lease_recovered_count"] == 0 and t.posted == []


def test_a_missing_run_counts_as_terminated():
    t = issue_1396_shape()
    t._runs[555] = "missing"
    assert run(t)["parked_lease_recovered_count"] == 1


def test_leases_already_settled_are_left_alone():
    t = issue_1396_shape()
    t._comments[1].append(settlement_comment(created=NOW - timedelta(minutes=10)))
    assert run(t)["parked_lease_recovered_count"] == 0 and t.posted == []


@pytest.mark.parametrize("labels", [("oc-queued",), ("oc-running", "oc-blocked"), ("oc-done",)])
def test_only_parked_issues_without_a_running_label_are_considered(labels):
    t = issue_1396_shape()
    t.issues[1]["labels"] = list(labels)
    assert run(t)["parked_lease_recovered_count"] == 0


def test_a_receipt_from_someone_else_does_not_count_as_settlement():
    t = issue_1396_shape()
    forged = denied_release(900, comment_id=930)
    forged["user"] = {"login": "jsp1440"}
    t._comments[1].append(forged)
    assert run(t)["parked_lease_recovered"][0]["lease_comment_id"] == 900


def test_a_state_change_before_writing_is_an_error_not_a_receipt():
    t = issue_1396_shape()
    original = t.issue

    def moved(number):
        current = original(number)
        if t.posted == [] and getattr(moved, "calls", 0) >= 1:
            current["labels"] = ["oc-queued"]
        moved.calls = getattr(moved, "calls", 0) + 1
        return current

    t.issue = moved
    report = run(t)
    assert t.posted == []
    assert report["errors"] == [{"issue": 1, "reason": "parked_lease_unconfirmed",
                                 "error_type": "ValueError"}]


def test_dry_run_writes_nothing():
    t = issue_1396_shape()
    report = run(t, dry_run=True)
    assert report["parked_lease_recovered"][0]["dry_run"] is True and t.posted == []


def test_each_wave_reads_a_bounded_window_and_every_issue_is_reached():
    numbers = list(range(10, 28))
    windows = [recon.parked_scan_window(numbers, run_id) for run_id in range(len(numbers))]
    assert all(len(w) == recon.PARKED_SCAN_PER_WAVE for w in windows)
    assert set().union(*windows) == set(numbers)
    assert recon.parked_scan_window([5, 3], 99) == [3, 5]


def test_running_and_validating_issues_are_not_read_again_as_parked():
    t = issue_1396_shape()
    t.issues[1]["labels"] = ["oc-validating", "oc-blocked"]
    read = []
    original = t.comments
    t.comments = lambda n: read.append(n) or original(n)
    run(t)
    assert read.count(1) == 1


def test_the_output_reports_the_parked_count(tmp_path, monkeypatch):
    t = issue_1396_shape()
    monkeypatch.setattr(recon, "GitHubTransport", lambda repo: t)
    output = tmp_path / "out"
    assert recon.main(["--repository", REPO, "--run-id", "42", "--github-output", str(output), "--dry-run"]) == 0
    assert "parked_lease_recovered_count=1" in output.read_text()


def governor_block(run_id, *, comment_id=940):
    return {"id": comment_id, "user": BOT, "created_at": (NOW - timedelta(minutes=40)).isoformat(),
            "body": "[OC-AUTO] Swarm governor blocked provider execution before credentials were "
            f"initialized. reason=BLOCKED_DAILY_BUDGET_EXCEEDED; packet={'ab' * 8}. "
            f"Run https://github.com/{REPO}/actions/runs/{run_id}."}


@pytest.mark.parametrize(
    ("receipt", "released"),
    [
        (lambda: governor_block(555), False),
        (lambda: governor_block(999), True),
        (lambda: {"id": 950, "user": BOT, "created_at": (NOW - timedelta(minutes=30)).isoformat(),
                  "body": "[OC-SWARM-V4] Worker result validated; requested lease disposition: `"
                  + json.dumps({"disposition": "blocked", "lease_comment_id": 900,
                                "lease_id": f"{REPO}:555:1:1"}, sort_keys=True) + "`."}, False),
    ],
    ids=["governor-own-run", "governor-other-run", "worker-disposition-names-it"],
)
def test_bound_receipts_settle_only_the_claim_they_name(receipt, released):
    t = issue_1396_shape()
    t._comments[1].append(receipt())
    assert (run(t)["parked_lease_recovered_count"] == 1) is released


def test_the_classifier_itself_refuses_an_issue_that_is_also_running():
    """reconcile skips running issues first; the classifier must not rely on it."""
    t = issue_1396_shape()
    parked_and_running = issue(labels=("oc-blocked", "oc-running"))
    assert recon.classify_parked_leases(
        parked_and_running, t.comments(1), repository=REPO, run_status=t.run_status, now=NOW
    ) == []
    assert len(recon.classify_parked_leases(
        t.issue(1), t.comments(1), repository=REPO, run_status=t.run_status, now=NOW
    )) == 1
