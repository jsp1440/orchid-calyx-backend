from __future__ import annotations

from collections.abc import Mapping

from .github_agent_lifecycle import GitHubAgentDispatchRecord
from .github_proposal_mutation_adapter import GitHubTransport, GitHubTransportResponse


class GitHubCommentRepairGateway:
    """Production `RepairRequestGateway`.

    Reuses the exact same `@copilot` PR-comment continuation mechanism
    `GitHubCopilotCloudProvider._continue_existing_pr` already uses for
    `CONTINUE`-classified missions, rather than inventing a second repair
    system. Acts only on one known, already-durably-bound dispatch/PR - it
    never searches for or guesses a PR to comment on. The 3-unsuccessful-
    attempts-per-failure-class ceiling is enforced upstream by
    `record_repair_request`/`reconcile_agent_lifecycle`
    (`MAX_SAME_FAILURE_RETRIES`); this gateway is only ever called once that
    check has already passed, so it does not duplicate the ceiling itself.
    """

    def __init__(self, *, transport: GitHubTransport) -> None:
        self._transport = transport

    def request_repair(
        self,
        dispatch: GitHubAgentDispatchRecord,
        *,
        failure_class: str,
    ) -> str:
        if dispatch.pull_request_number is None:
            raise PermissionError("GITHUB_REPAIR_PR_REQUIRED")
        body = self._repair_comment(dispatch, failure_class=failure_class)
        response = self._transport.request(
            "POST",
            f"/repos/{dispatch.repository}/issues/{dispatch.pull_request_number}/comments",
            json_body={"body": body},
        )
        self._require_status(response, {201}, "GITHUB_REPAIR_COMMENT_FAILED")
        payload = self._mapping(response.payload)
        url = str(payload.get("html_url") or "")
        if not url:
            raise RuntimeError("GITHUB_REPAIR_COMMENT_URL_MISSING")
        return url

    @staticmethod
    def _repair_comment(dispatch: GitHubAgentDispatchRecord, *, failure_class: str) -> str:
        return (
            "@copilot This PR's required CI is failing and needs a fix. Continue this "
            "existing governed mission; do not create a competing PR or branch.\n\n"
            f"Mission: `{dispatch.mission_id}`\n"
            f"Failure class: `{failure_class}`\n"
            f"Repair attempt: {dispatch.repair_attempts + 1}\n\n"
            "Keep this PR draft. Do not merge, deploy, mutate production state, publish, "
            "change credentials, spend funds, force-push, or delete branches/repos."
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise TypeError("GITHUB_REPAIR_RESPONSE_INVALID")
        return value

    @staticmethod
    def _require_status(response: GitHubTransportResponse, allowed: set[int], code: str) -> None:
        if response.status_code not in allowed:
            raise RuntimeError(f"{code}:{response.status_code}")
