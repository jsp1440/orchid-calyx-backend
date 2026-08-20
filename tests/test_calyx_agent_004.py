from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_engineering.completion_loop import CompletionState
from app.calyx_engineering.completion_scheduler import EngineeringCompletionScheduler
from app.calyx_engineering.github import FileChange
from app.calyx_engineering.service import CalyxEngineeringService
from app.calyx_orchestrator.models import CalyxJob
from app.database import Base


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
            "autonomous_merge": False,
            "deployment": False,
        }


class StubLoop:
    state = CompletionState.WAITING_FOR_CI

    def __init__(self, client) -> None:
        self.client = client

    def advance(self, **kwargs) -> StubReceipt:
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
