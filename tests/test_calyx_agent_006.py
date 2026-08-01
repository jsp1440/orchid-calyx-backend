from __future__ import annotations

import json

import pytest

from app.calyx_engineering.github import FileChange
from app.calyx_engineering.provider import PatchRequest, StructuredPatchProvider
from app.calyx_engineering.repair_loop import BoundedRepairLoop


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class FakeClient:
    def __init__(self, *, failures: bool = True, advance_branch: bool = True) -> None:
        self.failures = failures
        self.advance_branch = advance_branch
        self.committed: list[tuple[str, FileChange]] = []
        self.head_sha = "abc"

    def pull_request(self, number: int) -> dict:
        return {"number": number, "state": "open", "draft": True, "head": {"ref": "calyx/test", "sha": self.head_sha}}

    def workflow_runs_for_head(self, _head_sha: str) -> list[dict]:
        if not self.failures:
            return []
        return [{"id": 1, "name": "CI", "status": "completed", "conclusion": "failure"}]

    def workflow_jobs(self, _run_id: int) -> list[dict]:
        return [{"id": 2, "name": "tests", "conclusion": "failure"}]

    def workflow_job_logs(self, _job_id: int) -> str:
        return "AssertionError: expected 2"

    def get_text_file(self, path: str, *, ref: str = "main") -> str:
        return f"{ref}:{path}"

    def put_file(self, branch: str, change: FileChange) -> dict:
        self.committed.append((branch, change))
        if self.advance_branch:
            self.head_sha = "commit"
        return {"commit": {"sha": "commit"}}


class FakeProvider:
    def __init__(self, changes: list[FileChange] | None = None) -> None:
        self.changes = changes if changes is not None else [FileChange("app/example.py", "VALUE = 2\n", "Fix failing assertion")]

    def generate(self, request: PatchRequest) -> list[FileChange]:
        assert request.attempt == 1
        assert request.failure_logs
        return self.changes


def test_structured_provider_parses_bounded_changes(monkeypatch):
    monkeypatch.setattr(
        "app.calyx_engineering.provider.urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {"changes": [{"path": "app/example.py", "content": "VALUE = 2\n", "message": "Fix value"}]}
        ),
    )
    provider = StructuredPatchProvider("https://provider.invalid")
    changes = provider.generate(PatchRequest("fix", {"app/example.py": "VALUE = 1\n"}, ["failed"], 1))
    assert changes == [FileChange("app/example.py", "VALUE = 2\n", "Fix value")]


def test_repair_loop_commits_provider_changes():
    client = FakeClient()
    result = BoundedRepairLoop(client, FakeProvider()).repair_once(
        pull_request_number=12,
        paths=["app/example.py"],
        objective="Correct the failing assertion",
        attempt=1,
    )
    assert result.status == "repair_committed_waiting_for_ci"
    assert result.commits == 1
    assert client.committed[0][0] == "calyx/test"


def test_repair_loop_does_not_change_green_or_pending_pr():
    result = BoundedRepairLoop(FakeClient(failures=False), FakeProvider()).repair_once(
        pull_request_number=12,
        paths=["app/example.py"],
        objective="Correct the failing assertion",
        attempt=1,
    )
    assert result.status == "repair_not_applied_no_failed_checks"
    assert result.commits == 0


def test_repair_loop_reports_no_generated_changes():
    result = BoundedRepairLoop(FakeClient(), FakeProvider(changes=[])).repair_once(
        pull_request_number=12,
        paths=["app/example.py"],
        objective="Correct the failing assertion",
        attempt=1,
    )
    assert result.status == "repair_not_applied_no_changes_generated"
    assert result.commits == 0


def test_repair_loop_refuses_success_when_branch_does_not_advance():
    result = BoundedRepairLoop(FakeClient(advance_branch=False), FakeProvider()).repair_once(
        pull_request_number=12,
        paths=["app/example.py"],
        objective="Correct the failing assertion",
        attempt=1,
    )
    assert result.status == "repair_not_applied_branch_unchanged"
    assert result.commits == 0


def test_repair_loop_enforces_three_attempt_limit():
    with pytest.raises(ValueError, match="REPAIR_ATTEMPT_LIMIT_EXCEEDED"):
        BoundedRepairLoop(FakeClient(), FakeProvider()).repair_once(
            pull_request_number=12,
            paths=["app/example.py"],
            objective="fix",
            attempt=4,
        )
