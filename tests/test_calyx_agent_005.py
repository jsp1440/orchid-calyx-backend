from __future__ import annotations

import base64

import pytest

from app.calyx_engineering.github import FileChange, GitHubEngineeringClient
from app.calyx_engineering.inspection import RepositoryInspector
from app.calyx_engineering.repair import BoundedCIInspector


class FakeClient:
    def get_text_file(self, path: str, *, ref: str = "main") -> str:
        return f"{ref}:{path}"

    def pull_request(self, number: int) -> dict:
        return {"number": number, "head": {"sha": "abc123"}}

    def workflow_runs_for_head(self, head_sha: str) -> list[dict]:
        assert head_sha == "abc123"
        return [{"id": 10, "name": "CI", "status": "completed", "conclusion": "failure"}]

    def workflow_jobs(self, run_id: int) -> list[dict]:
        assert run_id == 10
        return [{"id": 20, "name": "tests", "conclusion": "failure"}]

    def workflow_job_logs(self, job_id: int) -> str:
        assert job_id == 20
        return "pytest failed"


def test_repository_inspection_is_bounded():
    context = RepositoryInspector(FakeClient()).inspect(["app/main.py", "tests/test_app.py"])
    assert context.file_count == 2
    assert context.files["app/main.py"] == "main:app/main.py"
    with pytest.raises(ValueError, match="INSPECTION_PATH_LIMIT_EXCEEDED"):
        RepositoryInspector(FakeClient()).inspect([f"app/{index}.py" for index in range(21)])


def test_ci_failure_inspection_returns_logs():
    failures = BoundedCIInspector(FakeClient()).failed_checks(12)
    assert len(failures) == 1
    assert failures[0].workflow == "CI"
    assert failures[0].log_excerpt == "pytest failed"


def test_workflow_files_remain_blocked():
    with pytest.raises(ValueError, match="UNSAFE_ENGINEERING_PATH"):
        FileChange(".github/workflows/unsafe.yml", "name: bad", "bad").validate()


def test_get_text_file_decodes_base64(monkeypatch):
    client = GitHubEngineeringClient("owner/repo", token="token")

    def fake_request(method: str, path: str, payload: dict | None = None) -> dict:
        assert method == "GET"
        assert payload is None
        return {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(b"hello").decode(),
        }

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.get_text_file("app/example.py") == "hello"
