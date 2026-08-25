"""Idempotent status feedback for GitHub-backed Calyx research requests."""

from __future__ import annotations

from typing import Protocol


class IssueCommentClient(Protocol):
    def issue_comments(self, issue_number: int) -> list[dict]: ...

    def create_issue_comment(self, issue_number: int, body: str) -> dict: ...

    def update_issue_comment(self, comment_id: int, body: str) -> dict: ...


def upsert_research_status_comment(
    client: IssueCommentClient,
    *,
    issue_number: int,
    marker: str,
    body: str,
) -> dict[str, object]:
    if not marker.startswith("<!-- calyx-research-bridge:") or not marker.endswith(
        " -->"
    ):
        raise ValueError("GITHUB_RESEARCH_FEEDBACK_MARKER_INVALID")
    if marker not in body:
        raise ValueError("GITHUB_RESEARCH_FEEDBACK_MARKER_MISSING")
    if len(body.encode("utf-8")) > 16_000:
        raise ValueError("GITHUB_RESEARCH_FEEDBACK_TOO_LARGE")

    matching: list[dict] = []
    for comment in client.issue_comments(issue_number):
        if marker in str(comment.get("body") or ""):
            matching.append(comment)
    if len(matching) > 1:
        raise RuntimeError("GITHUB_RESEARCH_FEEDBACK_DUPLICATE_MARKERS")

    if matching:
        try:
            comment_id = int(matching[0]["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("GITHUB_RESEARCH_FEEDBACK_COMMENT_ID_INVALID") from exc
        result = client.update_issue_comment(comment_id, body)
        return {
            "status": "updated",
            "comment_id": int(result.get("id") or comment_id),
        }

    result = client.create_issue_comment(issue_number, body)
    try:
        comment_id = int(result["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("GITHUB_RESEARCH_FEEDBACK_COMMENT_ID_INVALID") from exc
    return {"status": "created", "comment_id": comment_id}
