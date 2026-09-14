"""ChatGPT Business / Codex Programmatic CodingAgentProvider.

Dispatches governed Orchid Continuum engineering missions to OpenAI Codex
using a ChatGPT Business workspace access token.

Authentication contract:
- ONLY accepts a CodexBusinessCredential (CALYX_CHATGPT_BUSINESS_CODEX_TOKEN).
- OPENAI_API_KEY path is prohibited; its presence fails closed.
- The token value is never included in logs, receipts, or error messages.
- Receipts record AUTH_MODE only.

Provider behaviour:
- NEW/CONVERGE/SUPERSEDE → POST to the Codex task creation endpoint.
  Returns a task_id / session_id that Codex uses to create a branch + PR.
- CONTINUE → POST an iteration instruction comment on the existing PR.
- ALREADY_DONE → raises; executor must not dispatch this.

The HTTP transport is injected so tests can supply a mock without any real
network call. The production transport (CodexRequestsTransport) reads its
authorization from the CodexBusinessCredential and never logs the value.

No paid API key is accepted. No model inference is triggered by this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .chatgpt_business_codex_credential import (
    AUTH_MODE_BUSINESS_TOKEN,
    CodexBusinessCredential,
    CodexCredentialError,
)
from .github_coding_executor import ConvergenceClass, DispatchRequest, DispatchResult

# ---------------------------------------------------------------------------
# Codex API surface (ChatGPT Business programmatic access)
# ---------------------------------------------------------------------------

CODEX_API_BASE = "https://api.openai.com/v1"
CODEX_TASK_ENDPOINT = "/codex/sessions"  # POST — creates an async coding session
CODEX_ITERATION_ENDPOINT = "/codex/sessions/{session_id}/iterations"  # POST — add instruction


@dataclass(frozen=True, slots=True)
class CodexTransportResponse:
    status_code: int
    payload: object


class CodexTransport(Protocol):
    """Injected HTTP transport. Secrets stay inside the implementation."""

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> CodexTransportResponse: ...


class CodexRequestsTransport:
    """Production HTTPS transport. Bearer token is never logged or repr'd."""

    def __init__(self, credential: CodexBusinessCredential) -> None:
        self._credential = credential

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> CodexTransportResponse:
        import requests  # local import — test runs never reach this

        url = f"{CODEX_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self._credential.bearer_value}",
            "Content-Type": "application/json",
            "X-Auth-Mode": self._credential.auth_mode,
        }
        resp = requests.request(
            method,
            url,
            headers=headers,
            data=json.dumps(json_body) if json_body is not None else None,
            timeout=60,
        )
        try:
            payload: object = resp.json()
        except Exception:
            payload = resp.text
        return CodexTransportResponse(status_code=resp.status_code, payload=payload)

    def __repr__(self) -> str:
        return f"CodexRequestsTransport(auth_mode={self._credential.auth_mode!r}, bearer=<redacted>)"


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class ChatGPTBusinessCodexProvider:
    """Dispatch governed missions to ChatGPT Business Codex programmatic API.

    NEW/CONVERGE/SUPERSEDE missions POST a coding session. Codex creates a
    branch and draft PR asynchronously. CONTINUE missions POST an iteration
    instruction to the existing session. ALREADY_DONE must not be dispatched.

    The credential object is received at construction; it is never stored in
    receipts, logs, or outputs. All receipt evidence uses AUTH_MODE only.

    No fallback to OPENAI_API_KEY is permitted. The constructor will accept
    only a CodexBusinessCredential whose auth_mode is AUTH_MODE_BUSINESS_TOKEN.
    """

    provider_name = "chatgpt-business-codex-programmatic"
    executor_class = "codex_cloud_session_or_iteration"

    def __init__(
        self,
        *,
        transport: CodexTransport,
        credential: CodexBusinessCredential,
        repository_allowlist: Sequence[str],
    ) -> None:
        allowlist = frozenset(
            item.strip() for item in repository_allowlist if item.strip()
        )
        if not allowlist:
            raise ValueError("CODEX_PROVIDER_REPOSITORY_ALLOWLIST_REQUIRED")
        if credential.auth_mode != AUTH_MODE_BUSINESS_TOKEN:
            raise CodexCredentialError(
                "CODEX_PROVIDER_CREDENTIAL_AUTH_MODE_INVALID: "
                "only chatgpt_business_codex_token is accepted"
            )
        self._transport = transport
        self._credential = credential
        self._repository_allowlist = allowlist

    # Receipt evidence: auth mode, never the secret value.
    def _auth_evidence(self) -> str:
        return f"auth_mode:{self._credential.auth_mode}"

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if request.repository not in self._repository_allowlist:
            raise PermissionError("CODEX_PROVIDER_REPOSITORY_NOT_ALLOWED")
        if request.base_ref != "main":
            raise PermissionError("CODEX_PROVIDER_BASE_REF_NOT_ALLOWED")
        if request.convergence_class == ConvergenceClass.ALREADY_DONE:
            raise PermissionError("CODEX_PROVIDER_ALREADY_DONE_MUST_NOT_DISPATCH")
        if request.convergence_class == ConvergenceClass.CONTINUE:
            return self._continue_existing_session(request)
        return self._create_coding_session(request)

    def _create_coding_session(self, request: DispatchRequest) -> DispatchResult:
        """POST a new Codex coding session for NEW/CONVERGE/SUPERSEDE missions."""
        payload: dict[str, Any] = {
            "mission_id": request.mission_id,
            "repository": request.repository,
            "base_branch": request.base_ref,
            "base_sha": request.base_sha,
            "objective": request.objective[:2000],
            "acceptance_criteria": list(request.acceptance_criteria),
            "validation_commands": list(request.validation_commands),
            "budget_class": request.budget_class.value,
            "convergence_class": request.convergence_class.value,
            "draft_pr": True,
            "authority_boundary": (
                "Draft PR only. No merge, deployment, production mutation, "
                "scientific publication, credential creation, spending, "
                "force-push, branch deletion, or repository deletion."
            ),
        }
        response = self._transport.request("POST", CODEX_TASK_ENDPOINT, json_body=payload)
        self._require_status(response, {200, 201, 202}, "CODEX_PROVIDER_SESSION_CREATE_FAILED")
        body = self._mapping(response.payload)
        session_id = self._nonempty_str(body.get("id") or body.get("session_id"), "CODEX_PROVIDER_SESSION_ID_MISSING")
        pr_number = self._optional_int(body.get("pull_request_number"))
        pr_url = self._optional_str(body.get("pull_request_url"))
        branch = self._optional_str(body.get("branch"))
        state = "session_created" if pr_number is None else "dispatched"

        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch=branch,
            issue_number=None,
            pull_request_number=pr_number,
            pull_request_url=pr_url,
            draft=True,
            head_sha=self._optional_str(body.get("head_sha")),
            state=state,
            validation_evidence=(
                f"codex-session:{session_id}",
                f"repo-commit:{request.repository}@{request.base_sha}",
                self._auth_evidence(),
            ),
        )

    def _continue_existing_session(self, request: DispatchRequest) -> DispatchResult:
        """POST an iteration instruction to an existing Codex session (CONTINUE)."""
        prs = request.continuation_pr_numbers
        if len(prs) != 1:
            raise PermissionError("CODEX_PROVIDER_CONTINUE_REQUIRES_ONE_PR")
        pr_number = prs[0]
        # Reuse the pr_number as the session reference for the iteration endpoint.
        path = f"/codex/prs/{pr_number}/iterations"
        payload: dict[str, Any] = {
            "mission_id": request.mission_id,
            "instruction": self._iteration_instruction(request),
            "draft_pr": True,
        }
        response = self._transport.request("POST", path, json_body=payload)
        self._require_status(response, {200, 201, 202}, "CODEX_PROVIDER_ITERATION_FAILED")
        body = self._mapping(response.payload)
        iteration_id = self._nonempty_str(
            body.get("id") or body.get("iteration_id"),
            "CODEX_PROVIDER_ITERATION_ID_MISSING",
        )
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
                f"codex-iteration:{iteration_id}",
                f"github-pr:{request.repository}#{pr_number}",
                f"repo-commit:{request.repository}@{request.base_sha}",
                self._auth_evidence(),
            ),
        )

    @staticmethod
    def _iteration_instruction(request: DispatchRequest) -> str:
        criteria = "\n".join(f"- {item}" for item in request.acceptance_criteria)
        validation = "\n".join(f"- `{item}`" for item in request.validation_commands)
        return (
            f"Continue this governed mission; do not create a competing PR.\n"
            f"Mission: {request.mission_id}\n"
            f"Objective: {request.objective}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"Validation:\n{validation}\n\n"
            "Keep the PR in draft. "
            "Do not merge, deploy, mutate production state, publish science, "
            "change credentials, spend funds, force-push, or delete branches/repos."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _require_status(
        response: CodexTransportResponse,
        allowed: set[int],
        code: str,
    ) -> None:
        if response.status_code not in allowed:
            raise RuntimeError(f"{code}:{response.status_code}")

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("CODEX_PROVIDER_RESPONSE_INVALID")
        return value

    @staticmethod
    def _nonempty_str(value: object, code: str) -> str:
        s = str(value or "").strip()
        if not s:
            raise RuntimeError(code)
        return s

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_str(value: object) -> str | None:
        s = str(value or "").strip()
        return s if s else None
