"""Injected transports exercise denied admissions; these are not live receipts."""

from __future__ import annotations

import copy
import json
import subprocess
from datetime import datetime, timezone

import pytest

from scripts import oc_control_plane_health as health
from scripts import oc_swarm_claim as claims

REPO = "jsp1440/orchid-calyx-backend"
NUMBER = 1371
RUN = 1001
ATTEMPT = 1
NOW = datetime(2026, 9, 12, 8, tzinfo=timezone.utc)


class DenialGitHub:
    """Stateful GitHub transport with faults at individual write boundaries."""

    def __init__(self):
        self.issue = {
            "number": NUMBER,
            "title": "Expose read-only observer diagnostics",
            "body": "OC-SWARM-WRITES: control-plane",
            "state": "OPEN",
            "labels": ["oc-queued", "oc-p4"],
        }
        self.comments = []
        self.calls = []
        self.fault = None

    def __call__(self, args, payload=None):
        self.calls.append((copy.deepcopy(args), copy.deepcopy(payload)))
        if args[:2] == ["issue", "view"]:
            assert int(args[2]) == NUMBER
            return copy.deepcopy(self.issue)
        if args[:2] == ["issue", "edit"]:
            assert int(args[2]) == NUMBER
            if self.fault != "label_noop":
                labels = set(self.issue["labels"])
                for i, arg in enumerate(args):
                    if arg == "--remove-label":
                        labels.discard(args[i + 1])
                    elif arg == "--add-label":
                        labels.add(args[i + 1])
                if self.fault == "foreign_gate":
                    labels.add("oc-owner-gate")
                self.issue["labels"] = sorted(labels)
            if self.fault == "label_timeout":
                raise subprocess.TimeoutExpired("redacted", 30)
            return None
        assert args[:2] == ["api", "--method"]
        if args[2] == "GET":
            number = int(args[3].rsplit("/", 1)[1])
            value = next(c for c in self.comments if c["id"] == number)
            result = copy.deepcopy(value)
            if self.fault == "receipt_readback" and number != self.comments[0]["id"]:
                result["body"] = "contradictory stored receipt"
            return result
        assert args[2] == "POST"
        assert args[3] == f"repos/{REPO}/issues/{NUMBER}/comments"
        receipt = {
            "id": 5000 + len(self.comments),
            "body": payload["body"],
            "user": {"login": "github-actions[bot]"},
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/{NUMBER}",
            "created_at": "2026-09-12T07:30:00Z",
        }
        self.comments.append(receipt)
        if self.fault == "receipt_timeout":
            raise subprocess.TimeoutExpired("redacted", 30)
        return copy.deepcopy(receipt)


@pytest.fixture
def admitted():
    transport = DenialGitHub()
    worker = {
        "issue_number": NUMBER,
        "reads": [],
        "writes": ["control-plane"],
        "dependencies": [],
    }
    result = claims.claim_workers(
        {"workers": [worker]},
        {"issues": [copy.deepcopy(transport.issue)]},
        repository=REPO,
        run_id=RUN,
        run_attempt=ATTEMPT,
        call=transport,
    )
    assert result["launch_count"] == 1
    transport.calls.clear()
    return transport


def park(transport, **overrides):
    options = {
        "repository": REPO,
        "run_id": RUN,
        "run_attempt": ATTEMPT,
        "comment_id": transport.comments[0]["id"],
        "reason": "BLOCKED_MONTHLY_BUDGET_EXCEEDED",
        "call": transport,
    }
    options.update(overrides)
    return claims.park_denied_worker(issue_number=NUMBER, **options)


def test_denied_claim_is_parked_with_confirmed_receipt_and_no_requeue(admitted):
    result = park(admitted)
    assert result is not None
    assert set(admitted.issue["labels"]) == {"oc-blocked", "oc-p4"}
    assert len(admitted.comments) == 2
    body = admitted.comments[-1]["body"]
    assert "BLOCKED_MONTHLY_BUDGET_EXCEEDED" in body
    assert str(admitted.comments[0]["id"]) in body
    assert f"{REPO}:{RUN}:{ATTEMPT}:{NUMBER}" in body
    assert "oc-queued" not in admitted.issue["labels"]
    writes = [args for args, _ in admitted.calls if args[:2] == ["issue", "edit"]]
    assert len(writes) == 1
    assert "--add-label" in writes[0] and "oc-blocked" in writes[0]
    assert any(
        args[:3] == ["api", "--method", "GET"] and args[3].endswith("/5001")
        for args, _ in admitted.calls
    )


@pytest.mark.parametrize(
    "change",
    [
        "run",
        "attempt",
        "comment",
        "body",
        "owner_gate",
        "queued",
        "closed",
        "foreign_author",
        "foreign_issue",
    ],
)
def test_stale_or_foreign_claim_cannot_be_parked(admitted, change):
    options = {}
    if change == "run":
        options["run_id"] = RUN + 1
    elif change == "attempt":
        options["run_attempt"] = ATTEMPT + 1
    elif change == "comment":
        admitted.comments[0]["id"] += 1
        options["comment_id"] = 5000
    elif change == "body":
        admitted.issue["body"] += "\nChanged task"
    elif change == "closed":
        admitted.issue["state"] = "CLOSED"
    elif change == "foreign_author":
        admitted.comments[0]["user"]["login"] = "untrusted-user"
    elif change == "foreign_issue":
        admitted.comments[0]["issue_url"] = (
            f"https://api.github.com/repos/{REPO}/issues/2"
        )
    else:
        admitted.issue["labels"].append(
            "oc-owner-gate" if change == "owner_gate" else "oc-queued"
        )
    with pytest.raises((ValueError, KeyError, StopIteration)):
        park(admitted, **options)
    assert not any(args[:2] == ["issue", "edit"] for args, _ in admitted.calls)
    assert len(admitted.comments) == 1


@pytest.mark.parametrize("fault", ["label_timeout", "label_noop", "foreign_gate"])
def test_unconfirmed_label_write_never_fabricates_release_or_retries(admitted, fault):
    admitted.fault = fault
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        park(admitted)
    assert len(admitted.comments) == 1
    edits = [args for args, _ in admitted.calls if args[:2] == ["issue", "edit"]]
    assert len(edits) == 1
    if fault == "foreign_gate":
        assert "oc-owner-gate" in admitted.issue["labels"]


@pytest.mark.parametrize("fault", ["receipt_timeout", "receipt_readback"])
def test_unconfirmed_receipt_never_reports_success_or_restores_queue(admitted, fault):
    admitted.fault = fault
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        park(admitted)
    assert set(admitted.issue["labels"]) == {"oc-blocked", "oc-p4"}
    assert (
        len([args for args, _ in admitted.calls if args[:2] == ["issue", "edit"]]) == 1
    )


def test_repeated_denial_does_not_write_another_release(admitted):
    park(admitted)
    before = copy.deepcopy(admitted.comments)
    with pytest.raises(ValueError):
        park(admitted)
    assert admitted.comments == before


def observe(comments):
    row = {
        "number": NUMBER,
        "labels": ["oc-blocked", "oc-p4"],
        "state": "open",
        "updated_at": "2026-09-12T07:45:00Z",
        "comments": len(comments),
    }
    data = {
        "git/ref/heads/oc-autonomous-integration": {"object": {"sha": "a" * 40}},
        "git/ref/heads/main": {"object": {"sha": "b" * 40}},
        "issues?state=open&per_page=100&page=1": [row],
        "pulls?state=open&base=oc-autonomous-integration&per_page=100&page=1": [],
        f"issues/{NUMBER}": row,
        f"issues/{NUMBER}/comments?per_page=100&page=1": comments,
        f"actions/runs/{RUN}": {
            "id": RUN,
            "repository": {"full_name": REPO},
            "status": "completed",
            "conclusion": "success",
            "head_sha": "a" * 40,
            "head_branch": "oc-autonomous-integration",
            "path": ".github/workflows/orchid-swarm-controller.yml",
        },
        f"actions/runs/{RUN}/jobs?per_page=100&page=1": {
            "jobs": [
                {
                    "runner_id": 42,
                    "conclusion": "success",
                    "steps": [{"conclusion": "success"}],
                }
            ]
        },
    }

    def read(endpoint):
        return copy.deepcopy(data[endpoint.removeprefix(f"repos/{REPO}/")])

    return health.collect_github_snapshot(REPO, RUN, read_json=read, now=NOW)


def legacy_denial(claim, *, run=RUN, repository=REPO, fingerprint=None):
    raw = json.loads(claim["body"].split("`")[1])
    fingerprint = fingerprint or raw["material_fingerprint"]
    return {
        "id": 6000,
        "user": {"login": "github-actions[bot]"},
        "body": "[OC-AUTO] Swarm governor blocked provider execution before credentials were initialized. "
        f"reason=BLOCKED_MONTHLY_BUDGET_EXCEEDED; packet={fingerprint}. "
        f"Run https://github.com/{repository}/actions/runs/{run}.",
    }


def test_real_legacy_governor_denial_retires_only_its_claim(admitted):
    first = admitted.comments[0]
    second = copy.deepcopy(first)
    second["id"] += 100
    second["body"] = (
        second["body"]
        .replace(f":{RUN}:", f":{RUN + 1}:")
        .replace(f"/runs/{RUN}.", f"/runs/{RUN + 1}.")
    )
    snapshot = observe([first, second, legacy_denial(first)])
    assert [lease["id"] for lease in snapshot["leases"]] == [second["id"]]
    assert any(
        v["type"] == "orphan_active_lease"
        for v in health.build_health(snapshot)["contract_health"]["violations"]
    )


@pytest.mark.parametrize(
    "change", ["run", "repository", "fingerprint", "author", "ambiguous"]
)
def test_unmatched_or_ambiguous_legacy_denial_cannot_hide_claims(admitted, change):
    claim = admitted.comments[0]
    kwargs = {"run": RUN + 1} if change == "run" else {}
    if change == "repository":
        kwargs["repository"] = "other/repo"
    elif change == "fingerprint":
        kwargs["fingerprint"] = "f" * 16
    denial = legacy_denial(claim, **kwargs)
    if change == "author":
        denial["user"]["login"] = "untrusted-user"
    rows = [claim]
    if change == "ambiguous":
        duplicate = copy.deepcopy(claim)
        duplicate["id"] += 100
        rows.append(duplicate)
    snapshot = observe([*rows, denial])
    assert len(snapshot["leases"]) == len(rows)


def test_modern_verified_denial_is_consumed_by_actual_observer(admitted):
    park(admitted)
    snapshot = observe(admitted.comments)
    assert snapshot["leases"] == []
    assert snapshot["dispatch_fingerprints"] == []


def test_missing_fingerprints_never_cancel_each_other_as_matching_evidence(admitted):
    park(admitted)
    claim = admitted.comments[0]
    raw = json.loads(claim["body"].split("`")[1])
    fingerprint = raw["material_fingerprint"]
    claim["body"] = (
        claim["body"]
        .replace(f'"{fingerprint}"', "null")
        .replace(f"packet={fingerprint}.", "")
    )
    admitted.comments[-1]["body"] = admitted.comments[-1]["body"].replace(
        f'"{fingerprint}"', "null"
    )
    snapshot = observe(admitted.comments)
    assert [lease["id"] for lease in snapshot["leases"]] == [5000]
    assert health.build_health(snapshot)["healthy"] is False


@pytest.mark.parametrize("change", ["id", "lease", "fingerprint", "author"])
def test_modern_denial_with_changed_binding_preserves_claim(admitted, change):
    park(admitted)
    denial = admitted.comments[-1]
    if change == "author":
        denial["user"]["login"] = "untrusted-user"
    else:
        raw = json.loads(admitted.comments[0]["body"].split("`")[1])
        old = {
            "id": "5000",
            "lease": raw["lease_id"],
            "fingerprint": raw["material_fingerprint"],
        }[change]
        new = {
            "id": "9999",
            "lease": f"{REPO}:9999:1:{NUMBER}",
            "fingerprint": "f" * 16,
        }[change]
        assert old in denial["body"]
        denial["body"] = denial["body"].replace(old, new)
    snapshot = observe(admitted.comments)
    assert [lease["id"] for lease in snapshot["leases"]] == [5000]
