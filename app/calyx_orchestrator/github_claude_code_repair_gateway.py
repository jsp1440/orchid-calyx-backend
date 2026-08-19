from __future__ import annotations

from collections.abc import Mapping

from .github_agent_lifecycle import GitHubAgentDispatchRecord
from .github_proposal_mutation_adapter import GitHubTransport, GitHubTransportResponse


class GitHubClaudeCodeRepairGateway:
    """Request a bounded repair from Claude Code on one known draft PR."""

    def __init__(self, *, transport: GitHubTransport, trigger_phrase: str = "@claude") -> None:
        trigger = trigger_phrase.strip()
        if not trigger:
            raise ValueError("CLAUDE_REPAIR_TRIGGER_REQUIRED")
        self._transport = transport
        self._trigger_phrase = trigger

    def request_repair(
        self,
        dispatch: GitHubAgentDispatchRecord,
        *,
        failure_class: str,
    ) -> str:
        if dispatch.pull_request_number is None:
            raise PermissionError("GITHUB_REPAIR_PR_REQUIRED")
        response = self._transport.request(
            "POST",
            f"/repos/{dispatch.repository}/issues/{dispatch.pull_request_number}/comments",
            json_body={
                "body": self._repair_comment(dispatch, failure_class=failure_class)
            },
        )
        self._require_status(response, {201}, "CLAUDE_REPAIR_COMMENT_FAILED")
        payload = self._mapping(response.payload)
        url = str(payload.get("html_url") or "")
        if not url:
            raise RuntimeError("CLAUDE_REPAIR_COMMENT_URL_MISSING")
        return url

    def _repair_comment(
        self,
        dispatch: GitHubAgentDispatchRecord,
        *,
        failure_class: str,
    ) -> str:
        return (
            f"{self._trigger_phrase} This draft PR's required CI is failing and needs a fix. "
            "Continue this existing governed mission; do not create a competing PR or branch.\n\n"
            f"Mission: `{dispatch.mission_id}`\n"
            f"Failure class: `{failure_class}`\n"
            f"Repair attempt: {dispatch.repair_attempts + 1}\n\n"
            "Read CLAUDE.md and AGENTS.md. Keep this PR draft. Do not merge, deploy, mutate "
            "production state, publish science, change credentials, spend funds, force-push, "
            "or delete branches/repos."
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise TypeError("CLAUDE_REPAIR_RESPONSE_INVALID")
        return value

    @staticmethod
    def _require_status(
        response: GitHubTransportResponse,
        allowed: set[int],
        code: str,
    ) -> None:
        if response.status_code not in allowed:
            raise RuntimeError(f"{code}:{response.status_code}")
