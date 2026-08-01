from __future__ import annotations

import pytest

from app.calyx_engineering.github import FileChange
from app.calyx_engineering.service import CalyxEngineeringService


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
