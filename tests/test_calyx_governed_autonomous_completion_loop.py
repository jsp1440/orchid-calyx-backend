from __future__ import annotations

from types import SimpleNamespace

from app.calyx_engineering.completion_loop import (
    CompletionState,
    GovernedAutonomousCompletionLoop,
)


class FakeClient:
    def __init__(self, *, runs: list[dict], draft: bool = True, state: str = "open") -> None:
        self.runs = runs
        self.draft = draft
        self.state = state
        self.sha = "head-before"

    def pull_request(self, number: int) -> dict:
        return {
            "number": number,
            "state": self.state,
            "draft": self.draft,
            "head": {"ref": "agent/test", "sha": self.sha},
        }

    def workflow_runs_for_head(self, head_sha: str) -> list[dict]:
        return self.runs


class FakeRepairLoop:
    def __init__(self, client: FakeClient, *, commits: int = 1, status: str = "repair_committed_waiting_for_ci") -> None:
        self.client = client
        self.commits = commits
        self.status = status
        self.calls: list[dict] = []

    def repair_once(self, **kwargs):
        self.calls.append(kwargs)
        if self.status == "repair_committed_waiting_for_ci":
            self.client.sha = "head-after"
        return SimpleNamespace(status=self.status, commits=self.commits)


def test_waits_while_ci_is_running():
    client = FakeClient(runs=[{"name": "suite-a", "status": "in_progress", "conclusion": None}])
    loop = GovernedAutonomousCompletionLoop(client)
    receipt = loop.advance(
        pull_request_number=7,
        repair_paths=["app/x.py"],
        objective="repair tests",
        attempt=1,
        repairs_authorized=True,
    )
    assert receipt.state == CompletionState.WAITING_FOR_CI
    assert receipt.next_action == "recheck_after_ci"
    assert receipt.autonomous_merge is False
    assert receipt.deployment is False


def test_green_ci_advances_only_to_merge_policy_gate():
    client = FakeClient(runs=[{"name": "suite-a", "status": "completed", "conclusion": "success"}])
    loop = GovernedAutonomousCompletionLoop(client)
    receipt = loop.advance(
        pull_request_number=8,
        repair_paths=["app/x.py"],
        objective="repair tests",
        attempt=1,
        repairs_authorized=True,
    )
    assert receipt.state == CompletionState.READY_FOR_MERGE
    assert receipt.next_action == "evaluate_merge_policy"
    assert receipt.autonomous_merge is False
    assert receipt.deployment is False


def test_failed_ci_without_authorization_does_not_write():
    client = FakeClient(runs=[{"name": "suite-a", "status": "completed", "conclusion": "failure"}])
    loop = GovernedAutonomousCompletionLoop(client)
    receipt = loop.advance(
        pull_request_number=9,
        repair_paths=["app/x.py"],
        objective="repair tests",
        attempt=1,
        repairs_authorized=False,
    )
    assert receipt.state == CompletionState.FAILED_REPAIRABLE
    assert receipt.next_action == "authorize_bounded_repair"


def test_authorized_failure_invokes_one_bounded_repair_then_waits_for_ci():
    client = FakeClient(runs=[{"name": "suite-a", "status": "completed", "conclusion": "failure"}])
    repair = FakeRepairLoop(client)
    loop = GovernedAutonomousCompletionLoop(client, repair_factory=lambda _: repair)
    receipt = loop.advance(
        pull_request_number=10,
        repair_paths=["app/x.py", "tests/test_x.py"],
        objective="repair tests",
        attempt=2,
        repairs_authorized=True,
    )
    assert len(repair.calls) == 1
    assert receipt.state == CompletionState.REPAIR_COMMITTED
    assert receipt.head_sha == "head-after"
    assert receipt.commits == 1
    assert receipt.next_action == "recheck_after_ci"


def test_repair_limit_halts_before_another_write():
    client = FakeClient(runs=[{"name": "suite-a", "status": "completed", "conclusion": "failure"}])
    repair = FakeRepairLoop(client)
    loop = GovernedAutonomousCompletionLoop(client, repair_factory=lambda _: repair)
    receipt = loop.advance(
        pull_request_number=11,
        repair_paths=["app/x.py"],
        objective="repair tests",
        attempt=4,
        repairs_authorized=True,
    )
    assert receipt.state == CompletionState.HALTED_REPAIR_LIMIT
    assert repair.calls == []
    assert receipt.next_action == "human_review_repair_limit"


def test_non_draft_or_closed_pr_halts_fail_closed():
    client = FakeClient(runs=[], draft=False)
    loop = GovernedAutonomousCompletionLoop(client)
    receipt = loop.advance(
        pull_request_number=12,
        repair_paths=["app/x.py"],
        objective="repair tests",
        attempt=1,
        repairs_authorized=True,
    )
    assert receipt.state == CompletionState.HALTED_UNSAFE_PR_STATE
    assert receipt.next_action == "human_review_pr_state"
