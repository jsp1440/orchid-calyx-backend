from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.calyx_orchestrator.github_research_feedback import (
    upsert_research_status_comment,
)


@dataclass
class FakeComments:
    comments: list[dict] = field(default_factory=list)

    def issue_comments(self, issue_number: int) -> list[dict]:
        assert issue_number == 101
        return list(self.comments)

    def create_issue_comment(self, issue_number: int, body: str) -> dict:
        assert issue_number == 101
        comment = {"id": 7001, "body": body}
        self.comments.append(comment)
        return comment

    def update_issue_comment(self, comment_id: int, body: str) -> dict:
        for comment in self.comments:
            if comment["id"] == comment_id:
                comment["body"] = body
                return comment
        raise AssertionError("comment not found")


def test_feedback_creates_then_updates_one_marked_comment() -> None:
    client = FakeComments()
    marker = "<!-- calyx-research-bridge:RSR-GH-ONE -->"
    created = upsert_research_status_comment(
        client,
        issue_number=101,
        marker=marker,
        body=f"{marker}\nQueued.",
    )
    updated = upsert_research_status_comment(
        client,
        issue_number=101,
        marker=marker,
        body=f"{marker}\nCompleted.",
    )
    assert created == {"status": "created", "comment_id": 7001}
    assert updated == {"status": "updated", "comment_id": 7001}
    assert len(client.comments) == 1
    assert client.comments[0]["body"].endswith("Completed.")


def test_feedback_refuses_ambiguous_duplicate_markers() -> None:
    marker = "<!-- calyx-research-bridge:RSR-GH-ONE -->"
    client = FakeComments(
        comments=[
            {"id": 1, "body": marker},
            {"id": 2, "body": marker},
        ]
    )
    with pytest.raises(
        RuntimeError, match="GITHUB_RESEARCH_FEEDBACK_DUPLICATE_MARKERS"
    ):
        upsert_research_status_comment(
            client,
            issue_number=101,
            marker=marker,
            body=f"{marker}\nQueued.",
        )
