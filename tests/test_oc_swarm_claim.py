import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.oc_swarm_claim import claim_workers, github, verify_worker_claim
from scripts.oc_swarm_write_set_verifier import parse_lease_claim


def issue(number=1, **updates):
    return {"number": number, "title": "Bounded repository work", "body": "",
            "state": "OPEN", "labels": ["oc-queued", "oc-p4"], **updates}


class GitHub:
    """Fault-injecting transport fixture, never live execution evidence."""

    def __init__(self, rows):
        self.rows = {r["number"]: deepcopy(r) for r in rows}
        self.comments = []
        self.edits = []
        self.fail_receipt = False
        self.mutate_after_receipt = False

    def __call__(self, args, payload=None):
        if args[:2] == ["issue", "view"]:
            return deepcopy(self.rows[int(args[2])])
        if args[:2] == ["issue", "edit"]:
            self.edits.append(args)
            row = self.rows[int(args[2])]
            row["labels"] = [x for x in row["labels"] if x != "oc-queued"] + ["oc-running"]
            return None
        assert args[:3] == ["api", "--method", "POST"]
        assert args[-2:] == ["--input", "-"]
        if self.fail_receipt:
            raise subprocess.TimeoutExpired("redacted", 30)
        receipt = {"id": len(self.comments) + 100, "body": payload["body"],
                   "user": {"login": "github-actions[bot]"}}
        self.comments.append(receipt)
        if self.mutate_after_receipt:
            self.rows[1]["labels"].append("oc-owner-gate")
        return receipt


def execute(rows, api=None):
    plan = {"workers": [{"issue_number": row["number"], "reads": [], "writes": ["control-plane"],
                         "dependencies": [9] if row.get("body") else []}
                        for row in rows if row["number"] != 9]}
    api = api or GitHub(rows)
    return claim_workers(plan, {"issues": rows}, repository="owner/repo", run_id=123,
                         run_attempt=2, call=api), api


def test_claim_removes_queued_preserves_priority_and_returns_only_confirmed_matrix():
    rows = [issue(), issue(2)]
    api = GitHub(rows)
    api.rows[2]["labels"] = ["oc-blocked"]
    result, _ = execute(rows, api)
    assert result["planned_count"] == 2
    assert result["launch_count"] == 1
    worker = result["matrix"]["include"][0]
    assert worker["issue_number"] == 1 and worker["lease_comment_id"] == 100
    assert set(api.rows[1]["labels"]) == {"oc-running", "oc-p4"}
    assert result["skipped"] == [{"issue": 2, "reason": "not_exclusively_queued"}]
    body = api.comments[0]["body"]
    assert f"packet={worker['material_fingerprint']}" in body
    assert "owner/repo:123:2:1" in body
    assert parse_lease_claim(body) == {"reads": [], "writes": ["control-plane"]}


@pytest.mark.parametrize("extra", ["oc-running", "oc-validating", "oc-blocked", "oc-done",
                                  "oc-owner-gate", "oc-runtime-backoff", "oc-repair-backoff"])
def test_conflicting_or_protected_state_never_claims(extra):
    result, api = execute([issue(labels=["oc-queued", extra])])
    assert result["launch_count"] == 0
    assert not api.edits and not api.comments


@pytest.mark.parametrize("update", [{"body": "changed contract"}, {"title": "new title"},
                                    {"labels": ["oc-queued", "oc-p1"]}, {"state": "CLOSED"}])
def test_plan_to_claim_races_fail_closed(update):
    rows = [issue()]
    api = GitHub(rows)
    api.rows[1].update(update)
    result, _ = execute(rows, api)
    assert result["launch_count"] == 0
    assert not api.edits


def test_dependency_reopened_after_plan_never_claims():
    rows = [issue(body="OC-SWARM-DEPENDS-ON: #9"), issue(9, state="CLOSED", labels=[])]
    api = GitHub(rows)
    api.rows[9]["state"] = "OPEN"
    result, _ = execute(rows, api)
    assert result["skipped"] == [{"issue": 1, "reason": "dependency_changed_since_plan"}]
    assert not api.edits


def test_still_satisfied_dependency_can_claim():
    result, _ = execute([issue(body="OC-SWARM-DEPENDS-ON: #9"), issue(9, state="CLOSED", labels=[])])
    assert result["launch_count"] == 1


def test_unknown_receipt_write_outcome_never_dispatches_or_retries():
    api = GitHub([issue()])
    api.fail_receipt = True
    result, _ = execute([issue()], api)
    assert result["matrix"] == {"include": []}
    assert result["healthy"] is False
    assert result["errors"] == [{"issue": 1, "phase": "receipt_write", "reason": "claim_unconfirmed"}]
    assert len(api.edits) == 1  # do not overwrite a concurrent actor with rollback


def test_owner_gate_added_during_claim_is_preserved_and_suppresses_handoff():
    api = GitHub([issue()])
    api.mutate_after_receipt = True
    result, _ = execute([issue()], api)
    assert result["launch_count"] == 0
    assert result["errors"][0]["phase"] == "confirmation"
    assert "oc-owner-gate" in api.rows[1]["labels"]


def test_health_contract_rejects_unowned_receipt():
    api = GitHub([issue()])

    def unowned(args, payload=None):
        value = api(args, payload)
        if args[0] == "api":
            value["user"] = {}
        return value

    result, _ = execute([issue()], unowned)
    assert result["launch_count"] == 0
    assert result["errors"][0]["phase"] == "confirmation"


def test_zero_worker_plan_still_emits_valid_empty_matrix():
    result, api = execute([])
    assert result["matrix"] == {"include": []} and result["healthy"]
    assert not api.edits


def test_worker_accepts_the_exact_confirmed_claim():
    result, api = execute([issue()])
    worker = result["confirmed"][0]
    assert verify_worker_claim(api.rows[1], api.comments[0], repository="owner/repo",
                               run_id=123, run_attempt=2, comment_id=worker["lease_comment_id"])


def test_repeated_claim_does_not_create_another_receipt_or_launch():
    rows = [issue()]
    api = GitHub(rows)
    first, _ = execute(rows, api)
    second, _ = execute(rows, api)
    assert first["launch_count"] == 1 and second["launch_count"] == 0
    assert len(api.comments) == 1 and len(api.edits) == 1


@pytest.mark.parametrize("change", ["run", "attempt", "id", "body", "owner_gate", "queued", "closed"])
def test_worker_rejects_stale_or_changed_claim_before_execution(change):
    _, api = execute([issue()])
    kwargs = {"repository": "owner/repo", "run_id": 123, "run_attempt": 2, "comment_id": 100}
    if change == "run":
        kwargs["run_id"] = 124
    elif change == "attempt":
        kwargs["run_attempt"] = 3
    elif change == "id":
        kwargs["comment_id"] = 101
    elif change == "body":
        api.rows[1]["body"] = "changed acceptance"
    elif change == "closed":
        api.rows[1]["state"] = "CLOSED"
    else:
        api.rows[1]["labels"].append("oc-owner-gate" if change == "owner_gate" else "oc-queued")
    with pytest.raises(ValueError):
        verify_worker_claim(api.rows[1], api.comments[0], **kwargs)


def test_transport_does_not_interpolate_issue_text_into_shell(monkeypatch):
    captured = {}

    def run(args, **kwargs):
        captured.update(args=args, **kwargs)
        return subprocess.CompletedProcess(args, 0, '{"id":100}')

    monkeypatch.setattr(subprocess, "run", run)
    payload = {"body": "$(do-not-execute) `literal`\ncontent"}
    assert github(["api", "--method", "POST", "repos/owner/repo/issues/1/comments", "--input", "-"], payload)["id"] == 100
    assert json.loads(captured["input"]) == payload
    assert "shell" not in captured and captured["check"] and captured["timeout"] == 30


def test_workflow_dispatches_confirmed_matrix_and_retains_partial_failure_evidence():
    text = (Path(__file__).parents[1] / ".github/workflows/orchid-swarm-controller.yml").read_text()
    assert "matrix: ${{ steps.claim.outputs.matrix }}" in text
    assert "launch_count: ${{ steps.claim.outputs.launch_count }}" in text
    assert "matrix: ${{ steps.plan.outputs.matrix }}" not in text
    assert "python3 -m scripts.oc_swarm_claim" in text
    assert "--run-attempt" in text
    assert "Retain claim handoff evidence\n        if: always()" in text
    assert "lease_comment_id: ${{ format('{0}', matrix.lease_comment_id) }}" in text
    assert "if: failure() && steps.lease.outputs.execute == 'true'" in text
    lane = (Path(__file__).parents[1] / ".github/workflows/orchid-completion-lane.yml").read_text()
    assert "LEASE_COMMENT_ID: ${{ inputs.lease_comment_id }}" in lane
    assert "--verify-issue" in lane and "--lease-comment-id" in lane
