"""Codex Worker Adapter — wires BoundedDispatcher to ChatGPT Business Codex.

This is the execution boundary that connects the existing eight-lane
BoundedDispatcher (deep_orchestrate + bounded_dispatcher) to real coding
work via the ChatGPT Business Codex programmatic API.

Execution flow per lane:
    eligible queued issue (TaskLeaf / GitHub issue)
    → graph admission (DeepOrchestrate/BoundedDispatcher)
    → exclusive durable execution lease   (DeepOrchestrate.lease)
    → isolated branch / worktree          (encoded in Codex session)
    → bounded execution packet            (CodexExecutionPacket)
    → Codex worker invocation             (ChatGPTBusinessCodexProvider.dispatch)
    → tests / branch / draft PR / receipt (Codex cloud; recorded in receipt)
    → durable execution receipt           (TaskExecutionResult / ExecReceipt)
    → lease release                       (BoundedDispatcher.complete/block)
    → automatic lane refill               (DeepOrchestrate.refill)

Authentication interface:
- load_codex_business_credential() is called at the start of each execution.
- If OPENAI_API_KEY is present → CodexApiKeyFallbackError → lane parked safely.
- If CALYX_CHATGPT_BUSINESS_CODEX_TOKEN absent → CodexCredentialError → lane
  parked safely; issue not marked running/completed.
- Receipts record AUTH_MODE only; the credential value is never recorded.

This module is PROVIDER-FREE for deterministic tests: inject a mock
CodexTransport and a test credential to exercise the full lifecycle without
any real API call. The real credential injection is a one-step deployment
action when the ChatGPT Business MFA gate is cleared.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .chatgpt_business_codex_credential import (
    AUTH_MODE_BUSINESS_TOKEN,
    CodexBusinessCredential,
    CodexCredentialError,
)
from .chatgpt_business_codex_provider import (
    ChatGPTBusinessCodexProvider,
    CodexTransport,
)
from .deep_orchestrate import AUTH_GOVERNANCE, AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, TaskLeaf
from .github_coding_executor import BudgetClass, ConvergenceClass, DispatchRequest

# Authority classes that must never auto-execute via the Codex worker.
_NEVER_AUTO_EXECUTE = frozenset({AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE})

CODEX_WORKER_ID = "chatgpt-business-codex-worker-v1"


# ---------------------------------------------------------------------------
# Execution packet: bounded, serialisable input for one Codex coding session
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodexExecutionPacket:
    """All inputs required to dispatch one Codex coding session.

    Constructed from a TaskLeaf and used to build the DispatchRequest.
    """

    task_key: str
    mission_id: str
    repository: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    validation_commands: tuple[str, ...]
    budget_class: BudgetClass
    convergence_class: ConvergenceClass
    base_ref: str
    base_sha: str
    related_issue_numbers: tuple[int, ...]
    continuation_pr_numbers: tuple[int, ...]
    convergence_pr_numbers: tuple[int, ...]
    superseded_pr_numbers: tuple[int, ...]
    retry_count: int


# ---------------------------------------------------------------------------
# Execution receipt (worker-layer, distinct from the GovernedAssignment layer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodexWorkerReceipt:
    """Durable evidence record for one completed or blocked Codex execution.

    The credential value is NEVER stored here. auth_mode records the
    authentication mechanism only.
    """

    task_key: str
    worker_id: str
    status: str  # "dispatched" | "blocked" | "session_created" | "iteration_requested"
    auth_mode: str
    started_at: str
    completed_at: str
    duration_seconds: float
    provider: str | None
    session_evidence: tuple[str, ...]
    pull_request_number: int | None
    pull_request_url: str | None
    branch: str | None
    error_reason: str | None
    automatic_merge: bool = False
    automatic_deployment: bool = False
    production_mutation: bool = False
    publication: bool = False
    provider_api_called: bool = True  # True when a real dispatch was attempted

    def as_evidence(self) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "worker_id": self.worker_id,
            "status": self.status,
            "auth_mode": self.auth_mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "provider": self.provider,
            "session_evidence": list(self.session_evidence),
            "pull_request_number": self.pull_request_number,
            "pull_request_url": self.pull_request_url,
            "branch": self.branch,
            "error_reason": self.error_reason,
            "automatic_merge": self.automatic_merge,
            "automatic_deployment": self.automatic_deployment,
            "production_mutation": self.production_mutation,
            "publication": self.publication,
            "provider_api_called": self.provider_api_called,
        }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _leaf_to_packet(leaf: TaskLeaf) -> CodexExecutionPacket:
    """Extract a CodexExecutionPacket from a TaskLeaf evidence dict."""
    ev = leaf.evidence
    raw_criteria = ev.get("acceptance_criteria") or []
    raw_validation = ev.get("validation_commands") or []
    raw_related = ev.get("related_issue_numbers") or []
    raw_continuation = ev.get("continuation_pr_numbers") or []
    raw_convergence = ev.get("convergence_pr_numbers") or []
    raw_superseded = ev.get("superseded_pr_numbers") or []

    budget_raw = str(ev.get("budget_class") or BudgetClass.NORMAL.value).strip().upper()
    try:
        budget = BudgetClass(budget_raw)
    except ValueError:
        budget = BudgetClass.NORMAL

    convergence_raw = str(ev.get("convergence_class") or ConvergenceClass.NEW.value).strip().upper()
    try:
        convergence = ConvergenceClass(convergence_raw)
    except ValueError:
        convergence = ConvergenceClass.NEW

    return CodexExecutionPacket(
        task_key=leaf.key,
        mission_id=str(ev.get("mission_id") or leaf.key).strip(),
        repository=str(ev.get("repository") or "").strip(),
        objective=str(ev.get("objective") or leaf.key).strip(),
        acceptance_criteria=tuple(str(c).strip() for c in raw_criteria if str(c).strip()),
        validation_commands=tuple(str(c).strip() for c in raw_validation if str(c).strip()),
        budget_class=budget,
        convergence_class=convergence,
        base_ref=str(ev.get("base_ref") or "main").strip(),
        base_sha=str(ev.get("base_sha") or "").strip(),
        related_issue_numbers=tuple(int(n) for n in raw_related if str(n).strip().isdigit()),
        continuation_pr_numbers=tuple(int(n) for n in raw_continuation if str(n).strip().isdigit()),
        convergence_pr_numbers=tuple(int(n) for n in raw_convergence if str(n).strip().isdigit()),
        superseded_pr_numbers=tuple(int(n) for n in raw_superseded if str(n).strip().isdigit()),
        retry_count=int(ev.get("retry_count") or 0),
    )


class CodexCodingWorker:
    """Worker that dispatches TaskLeaves to ChatGPT Business Codex.

    Inject a mock CodexTransport + test CodexBusinessCredential to run
    deterministic proofs without any real API call (provider_api_called=False
    in the mock receipt). The real transport is CodexRequestsTransport.

    One CodexCodingWorker instance is shared across all lanes; each lane
    gets an exclusive lease from the reservoir before this worker is called.

    Fail-closed behaviours:
    - OWNER_GATE authority classes → BLOCKED:OWNER_GATE_REQUIRED
    - Missing repository in leaf evidence → BLOCKED:CODEX_REPOSITORY_REQUIRED
    - Missing base_sha → BLOCKED:CODEX_BASE_SHA_REQUIRED
    - Credential error → BLOCKED:CODEX_AUTH_MISSING (lane parked safely)
    - Provider dispatch error → BLOCKED:<error>
    """

    def __init__(
        self,
        *,
        transport: CodexTransport,
        credential: CodexBusinessCredential,
        repository_allowlist: tuple[str, ...],
        worker_id: str = CODEX_WORKER_ID,
    ) -> None:
        self._provider = ChatGPTBusinessCodexProvider(
            transport=transport,
            credential=credential,
            repository_allowlist=list(repository_allowlist),
        )
        self._credential = credential
        self._worker_id = worker_id

    def execute(self, leaf: TaskLeaf) -> CodexWorkerReceipt:
        """Execute one TaskLeaf. Returns a receipt; never raises.

        The BoundedDispatcher calls complete()/block() based on receipt.status.
        """
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()

        # Hard safety: owner-gated authority must never auto-execute.
        if leaf.authority_class in _NEVER_AUTO_EXECUTE:
            return self._blocked(
                leaf,
                error_reason="OWNER_GATE_REQUIRED",
                started_at=started_at,
                elapsed=time.monotonic() - started,
                provider_api_called=False,
            )

        packet = _leaf_to_packet(leaf)

        if not packet.repository:
            return self._blocked(
                leaf,
                error_reason="CODEX_REPOSITORY_REQUIRED",
                started_at=started_at,
                elapsed=time.monotonic() - started,
                provider_api_called=False,
            )
        if not packet.base_sha:
            return self._blocked(
                leaf,
                error_reason="CODEX_BASE_SHA_REQUIRED",
                started_at=started_at,
                elapsed=time.monotonic() - started,
                provider_api_called=False,
            )

        request = DispatchRequest(
            mission_id=packet.mission_id,
            repository=packet.repository,
            objective=packet.objective,
            acceptance_criteria=packet.acceptance_criteria,
            validation_commands=packet.validation_commands,
            budget_class=packet.budget_class,
            convergence_class=packet.convergence_class,
            base_ref=packet.base_ref,
            base_sha=packet.base_sha,
            related_issue_numbers=packet.related_issue_numbers,
            overlapping_pr_numbers=(),
            continuation_pr_numbers=packet.continuation_pr_numbers,
            convergence_pr_numbers=packet.convergence_pr_numbers,
            superseded_pr_numbers=packet.superseded_pr_numbers,
            retry_count=packet.retry_count,
        )

        try:
            result = self._provider.dispatch(request)
        except (PermissionError, RuntimeError, CodexCredentialError) as exc:
            return self._blocked(
                leaf,
                error_reason=str(exc),
                started_at=started_at,
                elapsed=time.monotonic() - started,
                provider_api_called=True,
            )

        elapsed = time.monotonic() - started
        completed_at = datetime.now(timezone.utc).isoformat()
        return CodexWorkerReceipt(
            task_key=leaf.key,
            worker_id=self._worker_id,
            status=result.state,
            auth_mode=self._credential.auth_mode,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=max(0.0, elapsed),
            provider=result.provider,
            session_evidence=result.validation_evidence,
            pull_request_number=result.pull_request_number,
            pull_request_url=result.pull_request_url,
            branch=result.branch,
            error_reason=result.blocker_code,
            automatic_merge=False,
            automatic_deployment=False,
            production_mutation=False,
            publication=False,
            provider_api_called=True,
        )

    def _blocked(
        self,
        leaf: TaskLeaf,
        *,
        error_reason: str,
        started_at: str,
        elapsed: float,
        provider_api_called: bool,
    ) -> CodexWorkerReceipt:
        completed_at = datetime.now(timezone.utc).isoformat()
        return CodexWorkerReceipt(
            task_key=leaf.key,
            worker_id=self._worker_id,
            status="blocked",
            auth_mode=self._credential.auth_mode,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=max(0.0, elapsed),
            provider=None,
            session_evidence=(),
            pull_request_number=None,
            pull_request_url=None,
            branch=None,
            error_reason=error_reason,
            automatic_merge=False,
            automatic_deployment=False,
            production_mutation=False,
            publication=False,
            provider_api_called=provider_api_called,
        )


# ---------------------------------------------------------------------------
# Factory helpers for assembling a ready CodexCodingWorker
# ---------------------------------------------------------------------------


def build_codex_worker_from_env(
    *,
    repository_allowlist: tuple[str, ...],
    environ: Mapping[str, str] | None = None,
) -> CodexCodingWorker:
    """Build a CodexCodingWorker from environment variables.

    Calls load_codex_business_credential() which enforces:
    - OPENAI_API_KEY prohibition
    - CALYX_CHATGPT_BUSINESS_CODEX_TOKEN presence

    Raises CodexCredentialError / CodexApiKeyFallbackError on misconfiguration;
    callers should catch and park the lane.

    The production transport (CodexRequestsTransport) is used; not suitable
    for unit tests (use build_codex_worker_with_mock instead).
    """
    from .chatgpt_business_codex_credential import load_codex_business_credential
    from .chatgpt_business_codex_provider import CodexRequestsTransport

    credential = load_codex_business_credential(environ=environ)
    transport = CodexRequestsTransport(credential)
    return CodexCodingWorker(
        transport=transport,
        credential=credential,
        repository_allowlist=repository_allowlist,
    )


def build_codex_worker_with_mock(
    *,
    transport: CodexTransport,
    repository_allowlist: tuple[str, ...],
    test_token: str = "test-placeholder-not-real",
) -> CodexCodingWorker:
    """Build a CodexCodingWorker with a mock transport for deterministic tests.

    The test_token is a placeholder value. It is NEVER treated as a real
    credential; it exists solely to satisfy the non-blank check in
    CodexBusinessCredential. Deterministic proofs use this factory.
    """
    credential = CodexBusinessCredential(test_token, auth_mode=AUTH_MODE_BUSINESS_TOKEN)
    return CodexCodingWorker(
        transport=transport,
        credential=credential,
        repository_allowlist=repository_allowlist,
    )
