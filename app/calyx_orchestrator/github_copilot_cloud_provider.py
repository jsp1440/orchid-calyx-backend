from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .github_coding_executor import (
    ConvergenceClass,
    DispatchRequest,
    DispatchResult,
)
from .github_proposal_mutation_adapter import GitHubTransport, GitHubTransportResponse

COPILOT_ASSIGNEE = "copilot-swe-agent[bot]"


@dataclass(frozen=True, slots=True)
class CopilotAssignmentOptions:
    custom_agent: str = ""
    model: str = ""


class GitHubCopilotCloudProvider:
    """Dispatch governed missions to GitHub Copilot cloud agent.

    NEW/CONVERGE/SUPERSEDE missions create a dedicated mission issue assigned
    to Copilot. GitHub then opens a draft PR asynchronously. CONTINUE missions
    do not create another PR; they steer exactly one existing Copilot PR with an
    `@copilot` comment. The transport is injected so credentials remain outside
    mission state and outside logs/receipts.
    """

    provider_name = "github-copilot-cloud-agent"
    executor_class = "github_issue_assignment_or_pr_iteration"

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        repository_allowlist: Sequence[str],
        options: CopilotAssignmentOptions | None = None,
    ) -> None:
        allowlist = frozenset(item.strip() for item in repository_allowlist if item.strip())
        if not allowlist:
            raise ValueError("COPILOT_PROVIDER_REPOSITORY_ALLOWLIST_REQUIRED")
        self._transport = transport
        self._repository_allowlist = allowlist
        self._options = options or CopilotAssignmentOptions()

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if request.repository not in self._repository_allowlist:
            raise PermissionError("COPILOT_PROVIDER_REPOSITORY_NOT_ALLOWED")
        if request.base_ref != "main":
            raise PermissionError("COPILOT_PROVIDER_BASE_REF_NOT_ALLOWED")

        if request.convergence_class == ConvergenceClass.ALREADY_DONE:
            raise PermissionError("COPILOT_PROVIDER_ALREADY_DONE_MUST_NOT_DISPATCH")
        if request.convergence_class == ConvergenceClass.CONTINUE:
            return self._continue_existing_pr(request)
        return self._assign_issue(request)

    def _continue_existing_pr(self, request: DispatchRequest) -> DispatchResult:
        prs = request.continuation_pr_numbers
        if len(prs) != 1:
            raise PermissionError("COPILOT_PROVIDER_CONTINUE_REQUIRES_ONE_PR")
        pr_number = prs[0]
        body = self._iteration_comment(request)
        response = self._transport.request(
            "POST",
            f"/repos/{request.repository}/issues/{pr_number}/comments",
            json_body={"body": body},
        )
        self._require_status(response, {201}, "COPILOT_PROVIDER_PR_COMMENT_FAILED")
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

    def _assign_issue(self, request: DispatchRequest) -> DispatchResult:
        payload: dict[str, Any] = {
            "title": f"{request.mission_id} — {request.objective[:160]}",
            "body": self._issue_body(request),
            "assignees": [COPILOT_ASSIGNEE],
            "agent_assignment": {
                "target_repo": request.repository,
                "base_branch": request.base_ref,
                "custom_instructions": self._custom_instructions(request),
            },
        }
        if self._options.custom_agent:
            payload["agent_assignment"]["custom_agent"] = self._options.custom_agent
        if self._options.model:
            payload["agent_assignment"]["model"] = self._options.model

        response = self._transport.request(
            "POST",
            f"/repos/{request.repository}/issues",
            json_body=payload,
        )
        self._require_status(response, {201}, "COPILOT_PROVIDER_ISSUE_ASSIGNMENT_FAILED")
        body = self._mapping(response.payload)
        issue_number = self._positive_int(body.get("number"), "COPILOT_PROVIDER_ISSUE_NUMBER_INVALID")
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
            state="agent_assigned",
            validation_evidence=(
                f"github-issue:{request.repository}#{issue_number}",
                f"repo-commit:{request.repository}@{request.base_sha}",
            ),
        )

    @staticmethod
    def _custom_instructions(request: DispatchRequest) -> str:
        return (
            "Follow repository AGENTS.md and .github/copilot-instructions.md. "
            "Do not merge, deploy, mutate production data/knowledge graph, publish science, "
            "alter credentials, spend funds, force-push, or delete branches/repos. "
            f"Convergence class: {request.convergence_class.value}. "
            f"Budget class: {request.budget_class.value}. "
            "Keep the pull request draft. Run the mission validation commands and report exact evidence."
        )

    @classmethod
    def _issue_body(cls, request: DispatchRequest) -> str:
        lines = [
            "## Governed Calyx engineering mission",
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
                "## Permanent authority boundary",
                "Draft PR only. No merge/auto-merge, deployment, production migration/DB/KG mutation, "
                "taxonomy activation, scientific publication, credential creation/disclosure, spending, "
                "force-push, branch deletion, or repository deletion.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _iteration_comment(request: DispatchRequest) -> str:
        criteria = "\n".join(f"- {item}" for item in request.acceptance_criteria)
        validation = "\n".join(f"- `{item}`" for item in request.validation_commands)
        return (
            "@copilot Continue this existing governed mission; do not create a competing PR.\n\n"
            f"Mission: `{request.mission_id}`\n"
            f"Objective: {request.objective}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"Validation:\n{validation}\n\n"
            "Keep this PR draft. Do not merge, deploy, mutate production state, publish, change "
            "credentials, spend funds, force-push, or delete branches/repos."
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise RuntimeError("COPILOT_PROVIDER_RESPONSE_INVALID")
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
