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
    def __init__(self, *, failures: bool = True) -> None:
        self.failures = failures
        self.committed: list[tuple[str, FileChange]] = []

    def pull_request(self, number: int) -> dict:
        return {"number": number, "state": "open", "draft": True, "head": {"ref": "calyx/test", "sha": "abc"}}

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
        return {"commit": {"sha": "commit"}}


class FakeProvider:
    def generate(self, request: PatchRequest) -> list[FileChange]:
        assert request.attempt == 1
        assert request.failure_logs
        return [FileChange("app/example.py", "VALUE = 2\n", "Fix failing assertion")]


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
    assert result.status == "green_or_pending_no_repair_applied"
    assert result.commits == 0


def test_repair_loop_enforces_three_attempt_limit():
    with pytest.raises(ValueError, match="REPAIR_ATTEMPT_LIMIT_EXCEEDED"):
        BoundedRepairLoop(FakeClient(), FakeProvider()).repair_once(
            pull_request_number=12,
            paths=["app/example.py"],
            objective="fix",
            attempt=4,
        )
