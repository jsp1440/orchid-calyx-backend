from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_engineering import completion_worker
from app.calyx_engineering.completion_loop import (
    CompletionState,
    GovernedAutonomousCompletionLoop,
)
from app.calyx_engineering.completion_scheduler import EngineeringCompletionScheduler
from app.calyx_engineering.github import FileChange
from app.calyx_engineering.service import CalyxEngineeringService
from app.calyx_orchestrator.models import CalyxJob
from app.database import Base

REQUIRED_CHECKS = ["conversation", "validate"]


class FakeGitHubClient:
    def __init__(self) -> None:
        self.files: list[str] = []

    def default_branch_sha(self, branch: str = "main") -> str:
        return "abc123"

    def create_issue(self, title: str, body: str) -> dict:
        return {"number": 12, "html_url": "https://example.invalid/issues/12"}

    def create_branch(self, branch: str, base_sha: str) -> dict:
        return {"ref": branch, "sha": base_sha}

    def put_file(self, branch: str, change: FileChange) -> dict:
        self.files.append(change.path)
        return {"commit": {"sha": "def456"}}

    def open_pull_request(self, title: str, body: str, branch: str, base: str = "main") -> dict:
        return {"number": 34, "html_url": "https://example.invalid/pull/34"}


class CheckRunClient:
    def __init__(self, check_runs: list[dict]) -> None:
        self.check_runs = check_runs

    def pull_request(self, number: int) -> dict:
        return {
            "number": number,
            "state": "open",
            "draft": True,
            "head": {"ref": "agent/example", "sha": "abc123"},
        }

    def check_runs_for_head(self, head_sha: str) -> list[dict]:
        assert head_sha == "abc123"
        return self.check_runs


class NeverRepair:
    def repair_once(self, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("repair must not run")


class StubReceipt:
    def __init__(self, state: CompletionState) -> None:
        self.state = state

    def to_dict(self) -> dict:
        return {
            "pull_request_number": 1041,
            "head_sha": "abc123",
            "branch": "agent/example",
            "state": self.state.value,
            "attempt": 1,
            "attempt_limit": 3,
            "failed_workflows": [],
            "pending_workflows": [],
            "successful_workflows": [],
            "commits": 1 if self.state == CompletionState.REPAIR_COMMITTED else 0,
            "next_action": "recheck_after_ci",
            "required_checks_known": True,
            "infrastructure_failure": False,
            "autonomous_merge": False,
            "deployment": False,
        }


class StubLoop:
    state = CompletionState.WAITING_FOR_CI

    def __init__(self, client) -> None:
        self.client = client

    def advance(self, **kwargs) -> StubReceipt:
        assert kwargs["required_checks"] == REQUIRED_CHECKS
        return StubReceipt(self.state)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CalyxJob.__table__])
    return sessionmaker(bind=engine)()


def _completion_scheduler(db) -> EngineeringCompletionScheduler:
    return EngineeringCompletionScheduler(
        db,
        FakeGitHubClient(),
        loop_factory=StubLoop,
    )


def _queued_completion_job(db) -> CalyxJob:
    return _completion_scheduler(db).enqueue(
        owner="owner",
        pull_request_number=1041,
        repair_paths=["app/example.py"],
        objective="Keep the draft PR moving through CI.",
        repairs_authorized=True,
        required_checks=REQUIRED_CHECKS,
    )


def test_proposal_is_draft_only():
    proposal = CalyxEngineeringService().propose(
        finding_id="12345678-abcd",
        title="Repair queue fencing",
        summary="A stale worker can write.",
        recommendation="Fence the update by lease token.",
    )
    assert proposal.branch.startswith("calyx/12345678-")
    assert proposal.to_dict()["autonomous_merge"] is False
    assert proposal.to_dict()["production_deployment"] is False


def test_execution_requires_preproduction_enablement(monkeypatch):
    monkeypatch.delenv("CALYX_ENGINEERING_ENABLED", raising=False)
    monkeypatch.delenv("CALYX_ENGINEERING_MODE", raising=False)
    service = CalyxEngineeringService(client=FakeGitHubClient())
    proposal = service.propose(
        finding_id="finding-1",
        title="Bounded change",
        summary="Summary",
        recommendation="Recommendation",
    )
    with pytest.raises(RuntimeError, match="CALYX_ENGINEERING_DISABLED"):
        service.execute(
            proposal=proposal,
            changes=[FileChange("app/example.py", "value = 1\n", "Add example")],
            approved=True,
        )


def test_execution_opens_issue_branch_commits_and_draft_pr(monkeypatch):
    monkeypatch.setenv("CALYX_ENGINEERING_ENABLED", "true")
    monkeypatch.setenv("CALYX_ENGINEERING_MODE", "preproduction")
    client = FakeGitHubClient()
    service = CalyxEngineeringService(client=client)
    proposal = service.propose(
        finding_id="finding-2",
        title="Bounded change",
        summary="Summary",
        recommendation="Recommendation",
    )
    result = service.execute(
        proposal=proposal,
        changes=[FileChange("app/example.py", "value = 1\n", "Add example")],
        approved=True,
    )
    assert result["status"] == "draft_pull_request_opened"
    assert result["issue_number"] == 12
    assert result["pull_request_number"] == 34
    assert result["autonomous_merge"] is False
    assert client.files == ["app/example.py"]


def test_change_rejects_workflow_and_parent_traversal():
    for path in ("../secret", ".github/workflows/unsafe.yml"):
        with pytest.raises(ValueError, match="UNSAFE_ENGINEERING_PATH"):
            FileChange(path, "x", "message").validate()


def test_completion_job_requires_explicit_repair_authorization():
    db = _session()
    scheduler = _completion_scheduler(db)
    with pytest.raises(PermissionError, match="ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"):
        scheduler.enqueue(
            owner="owner",
            pull_request_number=1041,
            repair_paths=["app/example.py"],
            objective="Repair CI failures.",
            repairs_authorized=False,
            required_checks=REQUIRED_CHECKS,
        )


def test_completion_job_requires_governed_check_roster():
    db = _session()
    scheduler = _completion_scheduler(db)
    with pytest.raises(ValueError, match="ENGINEERING_COMPLETION_REQUIRED_CHECKS_REQUIRED"):
        scheduler.enqueue(
            owner="owner",
            pull_request_number=1041,
            repair_paths=["app/example.py"],
            objective="Repair CI failures.",
            repairs_authorized=True,
            required_checks=[],
        )


def test_waiting_for_ci_requeues_without_consuming_repair_attempt():
    db = _session()
    _queued_completion_job(db)
    StubLoop.state = CompletionState.WAITING_FOR_CI
    result = _completion_scheduler(db).run_once(worker_id="worker-1")
    job = db.get(CalyxJob, result["job_id"])
    assert result["status"] == "queued"
    assert job is not None
    assert job.attempt_count == 0
    assert job.next_attempt_at is not None
    assert job.lease_token is None


def test_committed_repair_consumes_exactly_one_attempt():
    db = _session()
    _queued_completion_job(db)
    StubLoop.state = CompletionState.REPAIR_COMMITTED
    result = _completion_scheduler(db).run_once(worker_id="worker-1")
    job = db.get(CalyxJob, result["job_id"])
    assert result["status"] == "queued"
    assert job is not None
    assert job.attempt_count == 1
    assert result["result"]["repair_attempts_used"] == 1


def test_green_ci_completes_job_at_merge_gate():
    db = _session()
    _queued_completion_job(db)
    StubLoop.state = CompletionState.READY_FOR_MERGE
    result = _completion_scheduler(db).run_once(worker_id="worker-1")
    job = db.get(CalyxJob, result["job_id"])
    assert result["status"] == "completed"
    assert job is not None
    assert job.completed_at is not None
    assert result["result"]["state"] == "ready_for_merge"
    assert result["result"]["autonomous_merge"] is False


def test_scheduler_renews_lease_before_completion_cycle():
    db = _session()
    job = _queued_completion_job(db)
    claimed = _completion_scheduler(db).claim(worker_id="worker-1", lease_seconds=30)
    assert claimed is not None
    before = claimed.lease_expires_at
    token = str(claimed.lease_token)
    StubLoop.state = CompletionState.WAITING_FOR_CI
    _completion_scheduler(db).advance_claimed(
        claimed,
        worker_id="worker-1",
        lease_token=token,
    )
    assert before is not None
    job.status = "queued"
    job.next_attempt_at = None
    db.commit()
    claimed_again = _completion_scheduler(db).claim(worker_id="worker-2", lease_seconds=30)
    assert claimed_again is not None
    second_before = claimed_again.lease_expires_at
    scheduler = _completion_scheduler(db)
    scheduler._renew_lease(
        claimed_again,
        worker_id="worker-2",
        lease_token=str(claimed_again.lease_token),
    )
    db.refresh(claimed_again)
    assert second_before is not None
    assert claimed_again.lease_expires_at > second_before + timedelta(minutes=10)


def test_required_check_roster_fails_closed_when_check_is_missing():
    client = CheckRunClient(
        [{"name": "validate", "status": "completed", "conclusion": "success"}]
    )
    loop = GovernedAutonomousCompletionLoop(
        client,
        repair_factory=lambda client: NeverRepair(),
    )
    receipt = loop.advance(
        pull_request_number=1041,
        repair_paths=["app/example.py"],
        objective="Repair failures.",
        attempt=1,
        repairs_authorized=True,
        required_checks=REQUIRED_CHECKS,
    )
    assert receipt.state == CompletionState.WAITING_FOR_CI
    assert receipt.required_checks_known is False
    assert receipt.pending_workflows == ("conversation",)


def test_infrastructure_conclusion_never_invokes_repair():
    client = CheckRunClient(
        [
            {"name": "validate", "status": "completed", "conclusion": "cancelled"},
            {"name": "conversation", "status": "completed", "conclusion": "success"},
        ]
    )
    loop = GovernedAutonomousCompletionLoop(
        client,
        repair_factory=lambda client: NeverRepair(),
    )
    receipt = loop.advance(
        pull_request_number=1041,
        repair_paths=["app/example.py"],
        objective="Repair failures.",
        attempt=1,
        repairs_authorized=True,
        required_checks=REQUIRED_CHECKS,
    )
    assert receipt.state == CompletionState.WAITING_FOR_CI
    assert receipt.infrastructure_failure is True
    assert receipt.next_action == "retry_infrastructure_checks"
    assert receipt.commits == 0


def test_persisted_completion_job_stores_required_roster():
    db = _session()
    job = _queued_completion_job(db)
    payload = json.loads(job.request_text)
    assert payload["required_checks"] == REQUIRED_CHECKS
    assert payload["repairs_authorized"] is True


def test_standalone_completion_worker_requires_github_runtime_credentials(monkeypatch):
    monkeypatch.delenv("CALYX_ENGINEERING_ENABLED", raising=False)
    monkeypatch.delenv("CALYX_ENGINEERING_MODE", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert completion_worker.runtime_ready() is False

    monkeypatch.setenv("CALYX_ENGINEERING_ENABLED", "true")
    monkeypatch.setenv("CALYX_ENGINEERING_MODE", "preproduction")
    assert completion_worker.runtime_ready() is False

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    assert completion_worker.runtime_ready() is True


def test_standalone_worker_survives_transient_cycle_exception(monkeypatch):
    calls = {"count": 0}
    observed: list[dict] = []

    def failing_once(*, worker_id: str):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient")
        return {"executed": False, "reason": "idle"}

    def stop_after_two_sleeps(seconds: float):
        if calls["count"] >= 2:
            raise StopIteration

    monkeypatch.setattr(completion_worker, "run_once", failing_once)
    monkeypatch.setenv("CALYX_ENGINEERING_COMPLETION_WORKER_SECONDS", "10")
    with pytest.raises(StopIteration):
        completion_worker.run_forever(
            worker_id="test-worker",
            sleeper=stop_after_two_sleeps,
            on_cycle=observed.append,
        )

    assert calls["count"] == 2
    assert observed[0]["reason"] == "cycle_error"
    assert observed[0]["error_type"] == "RuntimeError"
    assert observed[1]["reason"] == "idle"
