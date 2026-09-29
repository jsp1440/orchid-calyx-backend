from __future__ import annotations

import copy
import subprocess

import pytest

from scripts.oc_blocked_release_apply import apply_action, apply_plan


def action(number: int = 7, blocker: str = "pr#6") -> dict:
    return {
        "action": "replace_queue_labels",
        "issue_number": number,
        "idempotency_key": f"blocked-release:{number}:{blocker}",
        "blocker": blocker,
        "requires_labels": ["oc-blocked"],
        "remove_labels": ["oc-blocked"],
        "add_labels": ["oc-queued"],
        "reason": "the blocker demonstrably cleared",
        "release_authorized": True,
    }


def plan(*actions: dict) -> dict:
    return {
        "schema": "oc.blocked-release-plan.v1",
        "mutates": False,
        "action_count": len(actions),
        "actions": list(actions),
    }


class FakeTransport:
    repository = "jsp1440/orchid-continuum-frontend"

    def __init__(self, issue: dict | None = None) -> None:
        self.current = issue or {
            "number": 7,
            "state": "OPEN",
            "labels": ["oc-blocked", "priority:p1", "science-safe"],
        }
        self.saved_comments: list[dict] = []
        self.edits = 0
        self.comment_writes = 0
        self.fail_edit_after_write = False
        self.fail_comment_after_write = False

    def issue(self, number: int) -> dict:
        return copy.deepcopy(self.current)

    def edit_labels(self, number: int, *, remove: list[str], add: list[str]) -> None:
        self.edits += 1
        labels = set(self.current["labels"])
        labels.difference_update(remove)
        labels.update(add)
        self.current["labels"] = sorted(labels)
        if self.fail_edit_after_write:
            raise subprocess.CalledProcessError(1, ["gh"])

    def comments(self, number: int) -> list[dict]:
        return copy.deepcopy(self.saved_comments)

    def comment(self, number: int, body: str) -> dict:
        self.comment_writes += 1
        saved = {"id": 900 + self.comment_writes, "body": body}
        self.saved_comments.append(saved)
        if self.fail_comment_after_write:
            raise subprocess.CalledProcessError(1, ["gh"])
        return copy.deepcopy(saved)


def test_apply_preserves_unrelated_labels_and_writes_exact_receipt() -> None:
    transport = FakeTransport()
    result = apply_action(
        transport,
        action(),
        controller_run_url="https://github.com/jsp1440/repo/actions/runs/123",
        dry_run=False,
    )

    assert result["outcome"] == "applied"
    assert result["receipt_comment_id"] == 901
    assert set(transport.current["labels"]) == {"oc-queued", "priority:p1", "science-safe"}
    assert result["receipt"]["repository"] == transport.repository
    assert result["receipt"]["issue_number"] == 7
    assert result["receipt"]["provider_calls"] == 0


def test_replay_is_a_noop_when_the_exact_receipt_exists() -> None:
    transport = FakeTransport()
    first = apply_action(transport, action(), controller_run_url="run://123", dry_run=False)
    second = apply_action(transport, action(), controller_run_url="run://123", dry_run=False)

    assert first["outcome"] == "applied"
    assert second["outcome"] == "already_applied"
    assert second["receipt_comment_id"] == first["receipt_comment_id"]
    assert transport.edits == 1
    assert transport.comment_writes == 1


def test_changed_state_without_receipt_fails_closed() -> None:
    transport = FakeTransport({"number": 7, "state": "OPEN", "labels": ["oc-queued"]})
    with pytest.raises(ValueError, match="receipt unconfirmed"):
        apply_action(transport, action(), controller_run_url="run://123", dry_run=False)


def test_owner_gate_outranks_an_authorized_release_plan() -> None:
    transport = FakeTransport(
        {"number": 7, "state": "OPEN", "labels": ["oc-blocked", "oc-owner-gate"]}
    )
    with pytest.raises(ValueError, match="owner-gated"):
        apply_action(transport, action(), controller_run_url="run://123", dry_run=False)
    assert transport.edits == 0


def test_dry_run_observes_but_never_writes() -> None:
    transport = FakeTransport()
    report = apply_plan(transport, plan(action()), controller_run_url="run://123")

    assert report["dry_run_count"] == 1
    assert report["applied_count"] == 0
    assert transport.edits == transport.comment_writes == 0


def test_an_uncertain_label_response_is_recovered_by_observation() -> None:
    transport = FakeTransport()
    transport.fail_edit_after_write = True
    result = apply_action(transport, action(), controller_run_url="run://123", dry_run=False)

    assert result["outcome"] == "applied"
    assert "oc-queued" in transport.current["labels"]


def test_an_uncertain_comment_response_is_recovered_by_exact_readback() -> None:
    transport = FakeTransport()
    transport.fail_comment_after_write = True
    result = apply_action(transport, action(), controller_run_url="run://123", dry_run=False)

    assert result["outcome"] == "applied"
    assert result["receipt_comment_id"] == 901


@pytest.mark.parametrize(
    "bad_plan",
    [
        {"schema": "wrong", "mutates": False, "action_count": 0, "actions": []},
        {"schema": "oc.blocked-release-plan.v1", "mutates": True, "action_count": 0, "actions": []},
        plan(action(), action()),
    ],
)
def test_malformed_or_duplicate_plans_are_rejected_before_writes(bad_plan: dict) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError):
        apply_plan(transport, bad_plan, controller_run_url="run://123", dry_run=False)
    assert transport.edits == transport.comment_writes == 0
