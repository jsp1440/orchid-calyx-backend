"""Provider-free coding adapter for bounded deterministic autonomous work.

This adapter intentionally does not implement general code synthesis. It admits
only an injected deterministic runner and validates its receipt against the
governed dispatch identity. No external model/provider API is reachable here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .github_coding_executor import DispatchRequest, DispatchResult

PROVIDER_FREE_EXECUTOR = "deterministic-local"


@dataclass(frozen=True, slots=True)
class DeterministicWorkerReceipt:
    branch: str
    issue_number: int
    pull_request_number: int
    pull_request_url: str
    head_sha: str
    validation_evidence: tuple[str, ...] = ()


class ProviderFreeCodingAdapter:
    """CodingAgentProvider backed only by a deterministic injected runner."""

    provider_name = "provider-free"
    executor_class = PROVIDER_FREE_EXECUTOR

    def __init__(
        self,
        runner: Callable[[DispatchRequest], DeterministicWorkerReceipt],
    ) -> None:
        self._runner = runner

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        receipt = self._runner(request)
        if not receipt.branch.strip():
            raise ValueError("PROVIDER_FREE_WORKER_BRANCH_REQUIRED")
        if receipt.issue_number <= 0 or receipt.pull_request_number <= 0:
            raise ValueError("PROVIDER_FREE_WORKER_GITHUB_LINEAGE_REQUIRED")
        if len(receipt.head_sha) != 40:
            raise ValueError("PROVIDER_FREE_WORKER_HEAD_SHA_INVALID")
        if not receipt.pull_request_url.startswith("https://github.com/"):
            raise ValueError("PROVIDER_FREE_WORKER_PR_URL_INVALID")

        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch=receipt.branch,
            issue_number=receipt.issue_number,
            pull_request_number=receipt.pull_request_number,
            pull_request_url=receipt.pull_request_url,
            draft=True,
            head_sha=receipt.head_sha,
            state="dispatched",
            validation_evidence=receipt.validation_evidence,
        )
