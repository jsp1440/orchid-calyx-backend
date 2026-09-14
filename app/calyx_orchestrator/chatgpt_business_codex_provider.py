"""ChatGPT Business / Codex CLI CodingAgentProvider.

TRANSPORT: Process/subprocess invoking the Codex CLI — NOT an HTTP REST API.

The ChatGPT Business Codex programmatic access surface is the Codex CLI
(@openai/codex npm package, github.com/openai/codex) running in an isolated
worker or private runner environment authenticated by a ChatGPT workspace
token.

There is NO documented OpenAI API Platform HTTP endpoint for this access
pattern. The following endpoints were invented in a prior draft and are
explicitly prohibited from reappearing:

    PROHIBITED (invented, undocumented):
        https://api.openai.com/v1/codex/sessions
        https://api.openai.com/v1/codex/sessions/{id}/iterations
        /codex/prs/{pr}/iterations
        Any other /v1/codex/* path

Official invocation surface (as of 2026-09, from openai/codex GitHub):
    CLI:  codex --approval-mode full-auto "<task>"
    NPM:  npx @openai/codex@latest --approval-mode full-auto "<task>"

INTENTIONALLY UNBOUND items (see class docstrings):
    CodexCLICommand.command        — exact CLI argv, TBD until verified
    CodexCredentialMapping.env_var — env var the Codex CLI reads for Business
                                     tokens; must NOT default to OPENAI_API_KEY

Tests use MockCodexProcessTransport which never invokes any subprocess or HTTP.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .chatgpt_business_codex_credential import (
    AUTH_MODE_BUSINESS_TOKEN,
    CodexBusinessCredential,
    CodexCredentialError,
)
from .github_coding_executor import ConvergenceClass, DispatchRequest, DispatchResult

# ---------------------------------------------------------------------------
# Prohibited endpoint sentinel — regression guard
# ---------------------------------------------------------------------------

# This tuple is imported by the regression test to confirm none of these
# strings appear in any production code path.
PROHIBITED_API_PLATFORM_ENDPOINTS: tuple[str, ...] = (
    "/v1/codex/sessions",
    "/codex/sessions",
    "/codex/prs/",
    "api.openai.com/v1/codex",
)


# ---------------------------------------------------------------------------
# Credential mapping (UNBOUND)
# ---------------------------------------------------------------------------


class CodexCredentialMappingError(CodexCredentialError):
    """Raised when the Codex CLI credential env-var mapping is unresolved."""


class CodexCredentialMapping:
    """Maps CALYX_CHATGPT_BUSINESS_CODEX_TOKEN to the env var the Codex CLI reads.

    The Codex CLI community release uses OPENAI_API_KEY (the paid Platform
    billing path — PROHIBITED for the ChatGPT Business lane).

    The exact env var for ChatGPT Business workspace tokens is NOT currently
    confirmed in sources available to this codebase. When official
    documentation or a verified integration test establishes the mapping,
    set BUSINESS_TOKEN_CLI_ENV_VAR to the correct name.

    DO NOT set this to "OPENAI_API_KEY". The credential check in
    chatgpt_business_codex_credential.py raises CodexApiKeyFallbackError
    when OPENAI_API_KEY is present specifically to block that path.
    """

    # The env var the Codex CLI reads for ChatGPT Business tokens.
    # Set to a string when the official interface is confirmed.
    # MUST NOT be "OPENAI_API_KEY".
    BUSINESS_TOKEN_CLI_ENV_VAR: str | None = None  # TBD — intentionally unbound

    @classmethod
    def is_bound(cls) -> bool:
        return cls.BUSINESS_TOKEN_CLI_ENV_VAR is not None

    @classmethod
    def build_cli_env(cls, credential: CodexBusinessCredential) -> dict[str, str]:
        """Build the subprocess environment containing the credential.

        Raises CodexCredentialMappingError when BUSINESS_TOKEN_CLI_ENV_VAR is
        unbound — the caller must not proceed to subprocess invocation.
        """
        if not cls.is_bound():
            raise CodexCredentialMappingError(
                "CODEX_CLI_CREDENTIAL_ENV_VAR_UNBOUND: The env var that the "
                "Codex CLI reads for a ChatGPT Business workspace token has not "
                "been verified from authoritative documentation. "
                "Set CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR to the "
                "correct name (NOT 'OPENAI_API_KEY'). "
                "Lane parked safely until resolved."
            )
        var_name = cls.BUSINESS_TOKEN_CLI_ENV_VAR
        if var_name == "OPENAI_API_KEY":
            raise CodexCredentialMappingError(
                "CODEX_CLI_CREDENTIAL_ENV_VAR_PROHIBITED: "
                "BUSINESS_TOKEN_CLI_ENV_VAR must not be set to OPENAI_API_KEY. "
                "That is the paid Platform billing path."
            )
        return {var_name: credential.bearer_value}


# ---------------------------------------------------------------------------
# CLI command (UNBOUND)
# ---------------------------------------------------------------------------


class CodexCLIUnboundError(RuntimeError):
    """Raised when the Codex CLI command is not yet configured."""


@dataclass
class CodexCLICommand:
    """The subprocess command to invoke the Codex CLI.

    The exact command is INTENTIONALLY UNBOUND until verified. Known candidate
    (from openai/codex GitHub, unverified for Business non-interactive mode):

        ["npx", "@openai/codex@latest", "--approval-mode", "full-auto", "--quiet"]

    Set `command` to the verified argv list before production use.
    """

    command: list[str] | None = None  # None = unbound

    # Suggested candidate — set this when verified:
    # command: list[str] = field(default_factory=lambda: [
    #     "npx", "@openai/codex@latest",
    #     "--approval-mode", "full-auto",
    #     "--quiet",
    # ])

    def is_bound(self) -> bool:
        return bool(self.command)

    def argv(self, *, task: str) -> list[str]:
        if not self.is_bound():
            raise CodexCLIUnboundError(
                "CODEX_CLI_COMMAND_UNBOUND: The Codex CLI command has not been "
                "configured. Set CodexCLICommand.command to the verified argv "
                "list (e.g. ['npx', '@openai/codex@latest', '--approval-mode', "
                "'full-auto']) before production use. Lane parked safely."
            )
        return list(self.command) + [task]


# ---------------------------------------------------------------------------
# Process transport protocol + implementations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodexProcessResult:
    """Result of one Codex CLI subprocess invocation."""

    exit_code: int
    stdout: str
    stderr: str
    branch: str | None = None
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    head_sha: str | None = None
    session_id: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class CodexProcessTransport(Protocol):
    """Injected transport for Codex CLI execution. Mock in tests; subprocess in prod."""

    def run(
        self,
        *,
        task: str,
        repository: str,
        base_ref: str,
        base_sha: str,
        env: dict[str, str],
    ) -> CodexProcessResult: ...


@dataclass
class MockCodexProcessTransport:
    """Deterministic mock. Never invokes subprocess, HTTP, or any real API."""

    responses: list[CodexProcessResult]
    calls: list[dict[str, str]] = field(default_factory=list)

    def run(
        self,
        *,
        task: str,
        repository: str,
        base_ref: str,
        base_sha: str,
        env: dict[str, str],
    ) -> CodexProcessResult:
        self.calls.append({
            "task": task,
            "repository": repository,
            "base_ref": base_ref,
            "base_sha": base_sha,
            # env keys are recorded but NOT values (never log credential values)
            "env_keys": ",".join(sorted(env.keys())),
        })
        return self.responses.pop(0)


class SubprocessCodexTransport:
    """Production Codex CLI subprocess transport.

    Invokes the Codex CLI in an isolated working directory. The credential
    is injected via the env var determined by CodexCredentialMapping — never
    via OPENAI_API_KEY.

    Both the command and credential mapping must be BOUND (non-None) before
    run() is callable; otherwise CodexCLIUnboundError or
    CodexCredentialMappingError is raised and the lane parks safely.
    """

    def __init__(
        self,
        *,
        cli_command: CodexCLICommand,
        working_dir: str | None = None,
        timeout_seconds: int = 1800,
    ) -> None:
        self._cli = cli_command
        self._working_dir = working_dir
        self._timeout = timeout_seconds

    def run(
        self,
        *,
        task: str,
        repository: str,
        base_ref: str,
        base_sha: str,
        env: dict[str, str],
    ) -> CodexProcessResult:
        argv = self._cli.argv(task=task)  # raises if unbound
        import os
        proc_env = {**os.environ, **env}
        # Remove OPENAI_API_KEY from the subprocess env as a hard safety measure;
        # the Business token must flow through the explicitly configured var only.
        proc_env.pop("OPENAI_API_KEY", None)

        try:
            proc = subprocess.run(
                argv,
                env=proc_env,
                cwd=self._working_dir,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CodexProcessResult(
                exit_code=124,
                stdout="",
                stderr=f"CODEX_CLI_TIMEOUT after {self._timeout}s",
            )
        except FileNotFoundError as exc:
            return CodexProcessResult(
                exit_code=127,
                stdout="",
                stderr=f"CODEX_CLI_NOT_FOUND: {exc}",
            )

        # Parse any structured output the CLI emits (branch/PR/head-sha).
        # Exact output format is TBD until CLI is verified; returns raw for now.
        return CodexProcessResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def __repr__(self) -> str:
        return f"SubprocessCodexTransport(command_bound={self._cli.is_bound()!r})"


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class CodexCLIAdapter:
    """Dispatch governed missions to the Codex CLI running in a private runner.

    Replaces the HTTP-API–based ChatGPTBusinessCodexProvider. The execution
    surface is a subprocess (the Codex CLI), not an API Platform HTTP call.

    NEW / CONVERGE / SUPERSEDE → invoke Codex CLI with the mission objective.
      Codex creates a branch, implements, tests, commits, opens a draft PR.
    CONTINUE → invoke Codex CLI with a continuation instruction against the
      existing PR branch.
    ALREADY_DONE → raises; executor must not dispatch.

    Both the CLI command and the credential env-var mapping must be BOUND
    before live dispatch. The mock transport is used for tests without binding.
    """

    provider_name = "chatgpt-business-codex-cli"
    executor_class = "codex_cli_subprocess_or_continuation"

    def __init__(
        self,
        *,
        transport: CodexProcessTransport,
        credential: CodexBusinessCredential,
        repository_allowlist: Sequence[str],
        credential_mapping: type[CodexCredentialMapping] = CodexCredentialMapping,
    ) -> None:
        allowlist = frozenset(
            item.strip() for item in repository_allowlist if item.strip()
        )
        if not allowlist:
            raise ValueError("CODEX_ADAPTER_REPOSITORY_ALLOWLIST_REQUIRED")
        if credential.auth_mode != AUTH_MODE_BUSINESS_TOKEN:
            raise CodexCredentialError(
                "CODEX_ADAPTER_CREDENTIAL_AUTH_MODE_INVALID: "
                "only chatgpt_business_codex_token is accepted"
            )
        self._transport = transport
        self._credential = credential
        self._repository_allowlist = allowlist
        self._credential_mapping = credential_mapping

    def _auth_evidence(self) -> str:
        return f"auth_mode:{self._credential.auth_mode}"

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if request.repository not in self._repository_allowlist:
            raise PermissionError("CODEX_ADAPTER_REPOSITORY_NOT_ALLOWED")
        if request.base_ref != "main":
            raise PermissionError("CODEX_ADAPTER_BASE_REF_NOT_ALLOWED")
        if request.convergence_class == ConvergenceClass.ALREADY_DONE:
            raise PermissionError("CODEX_ADAPTER_ALREADY_DONE_MUST_NOT_DISPATCH")
        if request.convergence_class == ConvergenceClass.CONTINUE:
            return self._continue_mission(request)
        return self._start_mission(request)

    def _build_cli_env(self) -> dict[str, str]:
        """Build the subprocess env. Raises if credential mapping is unbound."""
        return self._credential_mapping.build_cli_env(self._credential)

    def _task_prompt(self, request: DispatchRequest) -> str:
        criteria = "\n".join(f"- {c}" for c in request.acceptance_criteria)
        validation = "\n".join(f"- {v}" for v in request.validation_commands)
        return (
            f"Mission: {request.mission_id}\n"
            f"Repository: {request.repository}\n"
            f"Base: {request.base_ref}@{request.base_sha}\n"
            f"Convergence: {request.convergence_class.value}\n"
            f"Budget: {request.budget_class.value}\n\n"
            f"Objective:\n{request.objective}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"Validation commands:\n{validation}\n\n"
            "Authority boundary: Draft PR only. No merge, deployment, "
            "production mutation, scientific publication, credential creation, "
            "spending, force-push, branch deletion, or repository deletion."
        )

    def _continuation_prompt(self, request: DispatchRequest) -> str:
        prs = list(request.continuation_pr_numbers)
        criteria = "\n".join(f"- {c}" for c in request.acceptance_criteria)
        validation = "\n".join(f"- {v}" for v in request.validation_commands)
        return (
            f"Continue governed mission {request.mission_id} on PR {prs}.\n"
            f"Do not create a competing PR.\n\n"
            f"Objective:\n{request.objective}\n\n"
            f"Acceptance criteria:\n{criteria}\n\n"
            f"Validation:\n{validation}\n\n"
            "Keep draft. No merge, deploy, production mutation, publish, "
            "credential changes, spending, force-push, or branch deletion."
        )

    def _start_mission(self, request: DispatchRequest) -> DispatchResult:
        try:
            env = self._build_cli_env()
        except CodexCredentialMappingError as exc:
            raise PermissionError(f"CODEX_ADAPTER_CREDENTIAL_MAPPING_UNBOUND: {exc}") from exc

        result = self._transport.run(
            task=self._task_prompt(request),
            repository=request.repository,
            base_ref=request.base_ref,
            base_sha=request.base_sha,
            env=env,
        )
        state = "session_created" if result.pull_request_number is None else "dispatched"
        if not result.succeeded:
            state = "cli_failed"

        session_id = result.session_id or f"codex-proc-{request.mission_id}"
        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch=result.branch,
            issue_number=None,
            pull_request_number=result.pull_request_number,
            pull_request_url=result.pull_request_url,
            draft=True,
            head_sha=result.head_sha,
            state=state,
            blocker_code=None if result.succeeded else f"CODEX_CLI_EXIT_{result.exit_code}",
            validation_evidence=(
                f"codex-session:{session_id}",
                f"repo-commit:{request.repository}@{request.base_sha}",
                self._auth_evidence(),
            ),
        )

    def _continue_mission(self, request: DispatchRequest) -> DispatchResult:
        prs = request.continuation_pr_numbers
        if len(prs) != 1:
            raise PermissionError("CODEX_ADAPTER_CONTINUE_REQUIRES_ONE_PR")
        pr_number = prs[0]

        try:
            env = self._build_cli_env()
        except CodexCredentialMappingError as exc:
            raise PermissionError(f"CODEX_ADAPTER_CREDENTIAL_MAPPING_UNBOUND: {exc}") from exc

        result = self._transport.run(
            task=self._continuation_prompt(request),
            repository=request.repository,
            base_ref=request.base_ref,
            base_sha=request.base_sha,
            env=env,
        )
        state = "iteration_requested" if result.succeeded else "cli_failed"
        session_id = result.session_id or f"codex-iter-{request.mission_id}"
        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch=result.branch,
            issue_number=None,
            pull_request_number=pr_number,
            pull_request_url=f"https://github.com/{request.repository}/pull/{pr_number}",
            draft=True,
            state=state,
            blocker_code=None if result.succeeded else f"CODEX_CLI_EXIT_{result.exit_code}",
            validation_evidence=(
                f"codex-session:{session_id}",
                f"github-pr:{request.repository}#{pr_number}",
                f"repo-commit:{request.repository}@{request.base_sha}",
                self._auth_evidence(),
            ),
        )


# ---------------------------------------------------------------------------
# Back-compat alias (old name referenced in worker adapter)
# ---------------------------------------------------------------------------

# Keep the old class name as an alias so callers that import
# ChatGPTBusinessCodexProvider still compile; it is the CLI adapter now.
ChatGPTBusinessCodexProvider = CodexCLIAdapter
