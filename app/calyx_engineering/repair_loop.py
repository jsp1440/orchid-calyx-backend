from __future__ import annotations

from dataclasses import dataclass

from .github import GitHubEngineeringClient
from .inspection import RepositoryInspector
from .provider import PatchRequest, StructuredPatchProvider
from .repair import BoundedCIInspector


@dataclass(frozen=True)
class RepairResult:
    pull_request_number: int
    branch: str
    attempt: int
    commits: int
    failed_checks_observed: int
    status: str

    def to_dict(self) -> dict:
        return {
            "pull_request_number": self.pull_request_number,
            "branch": self.branch,
            "attempt": self.attempt,
            "attempt_limit": 3,
            "attempts_remaining": 3 - self.attempt,
            "commits": self.commits,
            "failed_checks_observed": self.failed_checks_observed,
            "status": self.status,
            "autonomous_merge": False,
            "deployment": False,
        }


class BoundedRepairLoop:
    def __init__(
        self,
        client: GitHubEngineeringClient,
        provider: StructuredPatchProvider,
    ) -> None:
        self.client = client
        self.provider = provider

    def repair_once(
        self,
        *,
        pull_request_number: int,
        paths: list[str],
        objective: str,
        attempt: int,
    ) -> RepairResult:
        if attempt < 1 or attempt > 3:
            raise ValueError("REPAIR_ATTEMPT_LIMIT_EXCEEDED")
        pull_request = self.client.pull_request(pull_request_number)
        if pull_request.get("state") != "open":
            raise ValueError("REPAIR_PULL_REQUEST_NOT_OPEN")
        if not pull_request.get("draft", False):
            raise ValueError("REPAIR_REQUIRES_DRAFT_PULL_REQUEST")
        branch = str(pull_request.get("head", {}).get("ref") or "")
        if not branch:
            raise ValueError("REPAIR_BRANCH_UNAVAILABLE")

        failures = BoundedCIInspector(self.client).failed_checks(pull_request_number, limit=5)
        if not failures:
            return RepairResult(
                pull_request_number=pull_request_number,
                branch=branch,
                attempt=attempt,
                commits=0,
                failed_checks_observed=0,
                status="green_or_pending_no_repair_applied",
            )

        context = RepositoryInspector(self.client).inspect(paths, ref=branch)
        changes = self.provider.generate(
            PatchRequest(
                objective=objective,
                repository_files=context.files,
                failure_logs=[failure.log_excerpt for failure in failures],
                attempt=attempt,
            )
        )
        commits = [self.client.put_file(branch, change) for change in changes]
        return RepairResult(
            pull_request_number=pull_request_number,
            branch=branch,
            attempt=attempt,
            commits=len(commits),
            failed_checks_observed=len(failures),
            status="repair_committed_waiting_for_ci",
        )
