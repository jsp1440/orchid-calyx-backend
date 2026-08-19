from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .github_coding_executor import ConvergenceClass, DispatchRequest, DispatchResult
from .github_proposal_mutation_adapter import GitHubTransport, GitHubTransportResponse

CLAUDE_TRIGGER = "@claude"


class GitHubClaudeCodeActionProvider:
    """Dispatch governed missions through Anthropic's Claude Code GitHub Action.

    The provider itself does not call Anthropic. It creates or comments on a GitHub
    issue/PR using the existing injected GitHub transport. A repository workflow
    containing ``anthropics/claude-code-action`` observes the ``@claude`` trigger
    and performs the coding session asynchronously.

    This keeps credentials in GitHub Actions secrets and keeps mission identity in
    Calyx/Brain. The provider grants no merge, deployment, production mutation,
    publication, credential, spending, force-push, or destructive authority.
    """

    provider_name = "anthropic-claude-code-github-action"
    executor_class = "github_issue_trigger_or_pr_iteration"

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        repository_allowlist: Sequence[str],
        trigger_phrase: str = CLAUDE_TRIGGER,
    ) -> None:
        allowlist = frozenset(
            item.strip() for item in repository_allowlist if item.strip()
        )
        if not allowlist:
            raise ValueError("CLAUDE_PROVIDER_REPOSITORY_ALLOWLIST_REQUIRED")
        trigger = trigger_phrase.strip()
        if not trigger:
            raise ValueError("CLAUDE_PROVIDER_TRIGGER_REQUIRED")
        self._transport = transport
        self._repository_allowlist = allowlist
        self._trigger_phrase = trigger

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if request.repository not in self._repository_allowlist:
            raise PermissionError("CLAUDE_PROVIDER_REPOSITORY_NOT_ALLOWED")
        if request.base_ref != "main":
            raise PermissionError("CLAUDE_PROVIDER_BASE_REF_NOT_ALLOWED")
        if request.convergence_class == ConvergenceClass.ALREADY_DONE:
            raise PermissionError("CLAUDE_PROVIDER_ALREADY_DONE_MUST_NOT_DISPATCH")
        if request.convergence_class == ConvergenceClass.CONTINUE:
            return self._continue_existing_pr(request)
        return self._create_trigger_issue(request)

    def _continue_existing_pr(self, request: DispatchRequest) -> DispatchResult:
        prs = request.continuation_pr_numbers
        if len(prs) != 1:
            raise PermissionError("CLAUDE_PROVIDER_CONTINUE_REQUIRES_ONE_PR")
        pr_number = prs[0]
        response = self._transport.request(
            "POST",
            f"/repos/{request.repository}/issues/{pr_number}/comments",
            json_body={"body": self._iteration_comment(request)},
        )
        self._require_status(response, {201}, "CLAUDE_PROVIDER_PR_COMMENT_FAILED")
        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch=None,
            issue_number=None,
            pull_request_number=pr_number,
            pull_request_url=f"https://github.com/{request.repository}/pull/{pr_number}",
            draft=True,
            state="iteration_requested",
            validation_evidence=(
                f"github-pr:{request.repository}#{pr_number}",
                f"repo-commit:{request.repository}@{request.base_sha}",
            ),
        )

    def _create_trigger_issue(self, request: DispatchRequest) -> DispatchResult:
        payload: dict[str, Any] = {
            "title": f"{self._trigger_phrase} {request.mission_id} — {request.objective[:150]}",
            "body": self._issue_body(request),
        }
        response = self._transport.request(
            "POST",
            f"/repos/{request.repository}/issues",
            json_body=payload,
        )
        self._require_status(response, {201}, "CLAUDE_PROVIDER_ISSUE_CREATE_FAILED")
        body = self._mapping(response.payload)
        issue_number = self._positive_int(
            body.get("number"), "CLAUDE_PROVIDER_ISSUE_NUMBER_INVALID"
        )
        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch=None,
            issue_number=issue_number,
            pull_request_number=None,
            pull_request_url=None,
            draft=True,
            state="agent_triggered",
            validation_evidence=(
                f"github-issue:{request.repository}#{issue_number}",
                f"repo-commit:{request.repository}@{request.base_sha}",
            ),
        )

    def _issue_body(self, request: DispatchRequest) -> str:
        lines = [
            self._trigger_phrase,
            "",
            "## Governed Orchid Continuum engineering mission",
            f"Mission: `{request.mission_id}`",
            f"Repository: `{request.repository}`",
            f"Reviewed base: `{request.base_ref}` @ `{request.base_sha}`",
            f"Convergence: **{request.convergence_class.value}**",
            f"Budget: **{request.budget_class.value}**",
            "",
            "## Objective",
            request.objective,
            "",
            "## Acceptance criteria",
        ]
        lines.extend(f"- {item}" for item in request.acceptance_criteria)
        lines.extend(["", "## Validation"])
        lines.extend(f"- `{item}`" for item in request.validation_commands)
        lines.extend(["", "## Existing work inspected"])
        lines.append(f"- Related issues: {list(request.related_issue_numbers)}")
        lines.append(f"- Overlapping PRs: {list(request.overlapping_pr_numbers)}")
        lines.append(f"- Continue: {list(request.continuation_pr_numbers)}")
        lines.append(f"- Converge: {list(request.convergence_pr_numbers)}")
        lines.append(f"- Supersede: {list(request.superseded_pr_numbers)}")
        lines.extend(
            [
                "",
                "## Execution contract",
                "Read `CLAUDE.md` and `AGENTS.md` before editing. Reuse the authoritative existing lineage when one exists. Continue implementation, testing, repair, commit, push, and draft-PR creation without routine owner relay. Stop after three unsuccessful attempts on the same deterministic failure class.",
                "",
                "## Permanent authority boundary",
                "Draft PR only. Do not merge or auto-merge, deploy production, mutate production DB/KG/scientific state, activate taxonomy, publish science, create/disclose credentials, spend funds, force-push, delete branches, or delete repositories.",
            ]
        )
        return "\n".join(lines)

    def _iteration_comment(self, request: DispatchRequest) -> str:
        criteria = "\n".join(f"- {item}" for item in request.acceptance_criteria)
        validation = "\n".join(f"- `{item}`" for item in request.validation_commands)
        return (
            f"{self._trigger_phrase} Continue this existing governed mission; do not create a competing PR.\n\n"
            f"Mission: `{request.mission_id}`\n"
            f"Objective: {request.objective}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"Validation:\n{validation}\n\n"
            "Read CLAUDE.md and AGENTS.md. Keep this PR draft. Do not merge, deploy, mutate production state, publish science, change credentials, spend funds, force-push, or delete branches/repos."
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("CLAUDE_PROVIDER_RESPONSE_INVALID")
        return value

    @staticmethod
    def _positive_int(value: object, code: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(code) from exc
        if number <= 0:
            raise RuntimeError(code)
        return number

    @staticmethod
    def _require_status(
        response: GitHubTransportResponse,
        allowed: set[int],
        code: str,
    ) -> None:
        if response.status_code not in allowed:
            raise RuntimeError(f"{code}:{response.status_code}")
