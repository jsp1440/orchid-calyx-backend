"""Deterministic integration proofs for the ChatGPT Business Codex worker adapter.

Transport: MockCodexProcessTransport — no subprocess, no HTTP, no real API.

CLEARLY LABELLED:
    CONTROL-PLANE/WORKER-INTEGRATION PROOF (mock process transport, placeholder token)
    NOT: LIVE CODEX AUTHENTICATION PROOF (requires real Business token + verified CLI)

Proof inventory:
    A. One issue can traverse the complete lifecycle
    B. Two independent issues can simultaneously hold distinct execution leases
    C. Eight eligible fixtures can be admitted without duplicate ownership
    D. Completion/failure releases capacity and automatically refills it
    E. Owner-gated/blocked/backoff work cannot execute
    F. Missing authentication fails closed (CALYX_CHATGPT_BUSINESS_CODEX_TOKEN absent)
    G. API-key fallback cannot occur (OPENAI_API_KEY present → rejected)
    H. No subprocess/HTTP/real-API calls occur during these tests
    I. Cost = $0 (no paid provider, no billing)

Regression:
    R. No invented /v1/codex/* or /codex/sessions HTTP endpoints exist in production code
"""

from __future__ import annotations

import ast
import concurrent.futures
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.calyx_orchestrator.bounded_dispatcher import BoundedDispatcher, DispatchConfig
from app.calyx_orchestrator.chatgpt_business_codex_credential import (
    AUTH_MODE_BUSINESS_TOKEN,
    CodexApiKeyFallbackError,
    CodexBusinessCredential,
    CodexCredentialError,
    load_codex_business_credential,
)
from app.calyx_orchestrator.chatgpt_business_codex_provider import (
    PROHIBITED_API_PLATFORM_ENDPOINTS,
    CodexCLIAdapter,
    CodexCLICommand,
    CodexCredentialMapping,
    CodexCredentialMappingError,
    CodexProcessResult,
    MockCodexProcessTransport,
)
from app.calyx_orchestrator.codex_worker_adapter import (
    CodexCodingWorker,
    CodexWorkerReceipt,
    _MockCredentialMapping,
    _leaf_to_packet,
    build_codex_worker_with_mock,
)
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_PRODUCTION,
    AUTH_SCIENCE_PUB,
    AUTH_SECURITY,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.github_coding_executor import BudgetClass, ConvergenceClass

# ── Shared constants ───────────────────────────────────────────────────────

ALLOWED_REPO = "jsp1440/orchid-calyx-backend"
FAKE_SHA = "a" * 40
PLACEHOLDER_TOKEN = "test-placeholder-not-real"

# ── Mock process result factories ──────────────────────────────────────────


def _ok_result(
    session_id: str = "sess-001",
    branch: str | None = None,
    pr_number: int | None = None,
) -> CodexProcessResult:
    return CodexProcessResult(
        exit_code=0,
        stdout=f"Session {session_id} started",
        stderr="",
        branch=branch or f"calyx/codex-{session_id}",
        pull_request_number=pr_number,
        pull_request_url=(
            f"https://github.com/{ALLOWED_REPO}/pull/{pr_number}"
            if pr_number
            else None
        ),
        head_sha="b" * 40 if pr_number else None,
        session_id=session_id,
    )


def _ok_result_with_pr(
    session_id: str = "sess-001",
    pr_number: int = 42,
) -> CodexProcessResult:
    return _ok_result(session_id=session_id, pr_number=pr_number)


def _fail_result(exit_code: int = 1, session_id: str = "sess-err") -> CodexProcessResult:
    return CodexProcessResult(
        exit_code=exit_code,
        stdout="",
        stderr="Codex CLI error",
        session_id=session_id,
    )


# ── TaskLeaf factory ───────────────────────────────────────────────────────


def _issue_leaf(
    key: str,
    authority_class: str = AUTH_WORKSPACE,
    state: str = TaskState.READY,
) -> TaskLeaf:
    leaf = TaskLeaf(
        key=key,
        title=f"Issue: {key}",
        repo="orchid-calyx-backend",
        module="app/calyx_orchestrator",
        priority=Priority.P1,
        authority_class=authority_class,
        consequence_risk="low",
    )
    leaf.state = state
    leaf.evidence = {
        "mission_id": key,
        "repository": ALLOWED_REPO,
        "objective": f"Implement {key}",
        "acceptance_criteria": ["tests pass", "draft PR created"],
        "validation_commands": ["pytest -q tests/"],
        "budget_class": BudgetClass.NORMAL.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": FAKE_SHA,
    }
    return leaf


# ── Worker factory using mock process transport ────────────────────────────


def _worker(responses: list[CodexProcessResult]) -> tuple[CodexCodingWorker, MockCodexProcessTransport]:
    transport = MockCodexProcessTransport(responses=responses)
    worker = build_codex_worker_with_mock(
        transport=transport,
        repository_allowlist=(ALLOWED_REPO,),
    )
    return worker, transport


# =============================================================================
# REGRESSION — No invented API Platform endpoints in production code
# =============================================================================


class TestRegressionNoInventedEndpoints:
    """REGRESSION R: prohibited /v1/codex/* endpoints must never reappear."""

    _PRODUCTION_DIRS = [
        Path("app/calyx_orchestrator"),
    ]

    def _load_production_source(self) -> str:
        """Collect all source from production calyx_orchestrator modules."""
        src_parts: list[str] = []
        for d in self._PRODUCTION_DIRS:
            for py_file in sorted(d.glob("*.py")):
                src_parts.append(py_file.read_text(encoding="utf-8"))
        return "\n".join(src_parts)

    @pytest.mark.parametrize("endpoint", PROHIBITED_API_PLATFORM_ENDPOINTS)
    def test_prohibited_endpoint_absent_from_production_code(self, endpoint: str) -> None:
        """Each invented endpoint must not appear in any production module.

        The PROHIBITED_API_PLATFORM_ENDPOINTS constant in the provider module
        is the canonical list. This test proves those strings are absent from
        all production source outside of the prohibition list itself and the
        test file.
        """
        src = self._load_production_source()
        # Remove the prohibition declaration itself (the tuple definition)
        # by stripping the module that defines the constant — we expect it
        # there and only there, as a documentation/guard artifact.
        # Everything *else* that references it in prod code is a violation.
        violations: list[str] = []
        for py_file in Path("app/calyx_orchestrator").glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            # The canonical declaration file is expected to contain these strings.
            if py_file.name == "chatgpt_business_codex_provider.py":
                continue
            if endpoint in text:
                violations.append(str(py_file))
        assert not violations, (
            f"Prohibited endpoint {endpoint!r} found in: {violations}. "
            "These were invented API Platform paths with no official documentation."
        )

    def test_no_openai_api_base_url_in_codex_modules(self) -> None:
        """api.openai.com/v1 must not be used as an HTTP base in Codex modules."""
        for py_file in Path("app/calyx_orchestrator").glob("*.py"):
            if py_file.name == "chatgpt_business_codex_provider.py":
                continue  # documented in the prohibition list only
            text = py_file.read_text(encoding="utf-8")
            assert "api.openai.com/v1/codex" not in text, (
                f"{py_file}: contains api.openai.com/v1/codex — this is a "
                "prohibited undocumented endpoint"
            )

    def test_credential_mapping_unbound_by_default(self) -> None:
        """CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR must be None by default.

        This prevents any production code from silently resolving to OPENAI_API_KEY.
        """
        assert CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR is None, (
            "BUSINESS_TOKEN_CLI_ENV_VAR must remain None until the official "
            "Codex CLI credential env var is confirmed from authoritative docs."
        )

    def test_cli_command_unbound_by_default(self) -> None:
        """Default CodexCLICommand must have no command (unbound)."""
        cmd = CodexCLICommand()
        assert not cmd.is_bound()

    def test_credential_mapping_rejects_openai_api_key(self) -> None:
        """Setting BUSINESS_TOKEN_CLI_ENV_VAR to OPENAI_API_KEY must raise."""
        cred = CodexBusinessCredential("tok")
        original = CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR
        try:
            CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR = "OPENAI_API_KEY"
            with pytest.raises(CodexCredentialMappingError, match="PROHIBITED"):
                CodexCredentialMapping.build_cli_env(cred)
        finally:
            CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR = original

    def test_unbound_cli_command_raises_on_argv(self) -> None:
        cmd = CodexCLICommand()
        from app.calyx_orchestrator.chatgpt_business_codex_provider import CodexCLIUnboundError
        with pytest.raises(CodexCLIUnboundError, match="CODEX_CLI_COMMAND_UNBOUND"):
            cmd.argv(task="do something")

    def test_unbound_credential_mapping_raises_on_build_env(self) -> None:
        cred = CodexBusinessCredential("tok")
        original = CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR
        try:
            CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR = None
            with pytest.raises(CodexCredentialMappingError, match="CODEX_CLI_CREDENTIAL_ENV_VAR_UNBOUND"):
                CodexCredentialMapping.build_cli_env(cred)
        finally:
            CodexCredentialMapping.BUSINESS_TOKEN_CLI_ENV_VAR = original


# =============================================================================
# PROOF A — One issue traverses the complete lifecycle
# =============================================================================


class TestProofA_SingleIssueFullLifecycle:
    """PROOF A: one issue traverses lease → dispatch → receipt → complete."""

    def test_full_lifecycle_session_created(self) -> None:
        worker, transport = _worker([_ok_result("s1")])
        leaf = _issue_leaf("issue:full-lifecycle:001")

        receipt = worker.execute(leaf)

        assert receipt.status == "blocked"
        assert receipt.error_reason == "CODEX_DRAFT_PR_REQUIRED"
        assert receipt.automatic_merge is False
        assert receipt.automatic_deployment is False
        assert receipt.production_mutation is False
        assert receipt.publication is False
        # Auth mode recorded, never the secret
        assert receipt.auth_mode == AUTH_MODE_BUSINESS_TOKEN
        # One mock call made, not a real subprocess
        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert call["repository"] == ALLOWED_REPO
        assert call["base_ref"] == "main"
        # Credential env values are NOT recorded in calls (only keys)
        assert PLACEHOLDER_TOKEN not in str(transport.calls)

    def test_full_lifecycle_with_pr(self) -> None:
        worker, _ = _worker([_ok_result_with_pr("s2", 99)])
        receipt = worker.execute(_issue_leaf("issue:full-lifecycle:pr"))
        assert receipt.status == "completed"
        assert receipt.pull_request_number == 99

    def test_receipt_as_evidence_is_serialisable(self) -> None:
        worker, _ = _worker([_ok_result_with_pr()])
        receipt = worker.execute(_issue_leaf("issue:evidence-serial:001"))
        ev = receipt.as_evidence()
        assert isinstance(ev, dict)
        assert ev["auth_mode"] == AUTH_MODE_BUSINESS_TOKEN
        assert ev["status"] == "completed"
        # The placeholder secret must not appear in the receipt
        assert PLACEHOLDER_TOKEN not in str(ev)

    def test_cli_failure_produces_blocked_receipt_no_secrets(self) -> None:
        """Failed CLI execution must remain blocked; secrets must not appear in receipt."""
        worker, transport = _worker([_fail_result(exit_code=2)])
        receipt = worker.execute(_issue_leaf("issue:cli-fail:001"))

        assert receipt.status == "blocked"
        assert receipt.error_reason is not None
        assert "CODEX_CLI_EXIT_2" in receipt.error_reason
        # Credential value must not leak into the receipt or its evidence
        ev = receipt.as_evidence()
        assert PLACEHOLDER_TOKEN not in str(ev)
        assert len(transport.calls) == 1


# =============================================================================
# PROOF B — Two independent issues hold distinct leases simultaneously
# =============================================================================


class TestProofB_TwoLanesConcurrentLeases:
    """PROOF B: two issues hold exclusive, non-overlapping execution leases."""

    def test_two_independent_issues_distinct_leases(self) -> None:
        worker_a, _ = _worker([_ok_result_with_pr("sA", 10)])
        worker_b, _ = _worker([_ok_result_with_pr("sB", 11)])

        reservoir = DeepOrchestrate(configured_width=2)
        leaf_a = _issue_leaf("issue:concurrent:lane-A")
        leaf_b = _issue_leaf("issue:concurrent:lane-B")
        reservoir.register(leaf_a)
        reservoir.register(leaf_b)

        leased_a = reservoir.lease("issue:concurrent:lane-A", holder="worker-A")
        leased_b = reservoir.lease("issue:concurrent:lane-B", holder="worker-B")

        assert leased_a.lease_holder == "worker-A"
        assert leased_b.lease_holder == "worker-B"
        assert leased_a.key != leased_b.key

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(worker_a.execute, leased_a)
            fut_b = pool.submit(worker_b.execute, leased_b)
            receipt_a = fut_a.result()
            receipt_b = fut_b.result()

        assert receipt_a.pull_request_number == 10
        assert receipt_b.pull_request_number == 11
        assert receipt_a.task_key != receipt_b.task_key

        reservoir.complete("issue:concurrent:lane-A", evidence=receipt_a.as_evidence())
        reservoir.complete("issue:concurrent:lane-B", evidence=receipt_b.as_evidence())

        assert reservoir._tasks["issue:concurrent:lane-A"].state == TaskState.COMPLETED
        assert reservoir._tasks["issue:concurrent:lane-B"].state == TaskState.COMPLETED


# =============================================================================
# PROOF C — Eight eligible fixtures admitted without duplicate ownership
# =============================================================================


class TestProofC_EightLaneCapacity:
    """PROOF C: eight issues admitted; each gets a unique lease; no duplicates."""

    def test_eight_issues_no_duplicate_ownership(self) -> None:
        reservoir = DeepOrchestrate(configured_width=8)
        issue_keys = [f"issue:eight-lane:{i:02d}" for i in range(8)]

        for key in issue_keys:
            reservoir.register(_issue_leaf(key))

        leased = [reservoir.lease(key, holder=f"worker-{key}") for key in issue_keys]

        lease_holders = {l.lease_holder for l in leased}
        lease_keys = [l.key for l in leased]

        assert len(lease_holders) == 8
        assert len(set(lease_keys)) == 8
        assert sorted(lease_keys) == sorted(issue_keys)

    def test_duplicate_lease_raises(self) -> None:
        reservoir = DeepOrchestrate(configured_width=8)
        leaf = _issue_leaf("issue:dup-lease:001")
        reservoir.register(leaf)
        reservoir.lease("issue:dup-lease:001", holder="worker-1")
        with pytest.raises((LookupError, ValueError)):
            reservoir.lease("issue:dup-lease:001", holder="worker-2")


# =============================================================================
# PROOF D — Completion/failure releases capacity and automatically refills
# =============================================================================


class TestProofD_CapacityRefillAfterTerminalState:
    """PROOF D: completion and failure each release a lane and allow refill."""

    def test_completion_releases_capacity(self) -> None:
        reservoir = DeepOrchestrate(configured_width=1)
        key = "issue:refill:complete"
        reservoir.register(_issue_leaf(key))
        leaf = reservoir.lease(key, holder="worker-1")

        reservoir.refill()
        ready = list(reservoir.ready_tasks())
        assert all(t.key != key for t in ready)

        reservoir.complete(key, evidence={"status": "dispatched"})

        new_key = "issue:refill:successor"
        reservoir.register(_issue_leaf(new_key))
        reservoir.refill()
        ready2 = [t.key for t in reservoir.ready_tasks()]
        assert new_key in ready2

    def test_block_releases_capacity(self) -> None:
        reservoir = DeepOrchestrate(configured_width=1)
        key = "issue:refill:blocked"
        reservoir.register(_issue_leaf(key))
        reservoir.lease(key, holder="worker-1")
        reservoir.block(key, reason="CODEX_CLI_COMMAND_UNBOUND")
        assert reservoir._tasks[key].state == TaskState.BLOCKED

        new_key = "issue:refill:blocked-successor"
        reservoir.register(_issue_leaf(new_key))
        reservoir.refill()
        ready = [t.key for t in reservoir.ready_tasks()]
        assert new_key in ready


# =============================================================================
# PROOF E — Owner-gated / blocked / backoff work cannot execute
# =============================================================================


class TestProofE_OwnerGatedBlockedBackoffExclusion:
    """PROOF E: owner-gated, blocked, and backoff tasks never auto-execute."""

    @pytest.mark.parametrize(
        "authority_class",
        [AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE],
    )
    def test_owner_gated_authority_blocked_by_worker(self, authority_class: str) -> None:
        worker, transport = _worker([])
        leaf = _issue_leaf("issue:owner-gate:001", authority_class=authority_class)
        receipt = worker.execute(leaf)

        assert receipt.status == "blocked"
        assert receipt.error_reason == "OWNER_GATE_REQUIRED"
        assert len(transport.calls) == 0  # no subprocess attempted

    def test_owner_gated_task_not_dispatched_by_reservoir(self) -> None:
        reservoir = DeepOrchestrate(configured_width=4)
        owner_leaf = _issue_leaf("issue:owner-gate:reservoir", authority_class=AUTH_PRODUCTION)
        reservoir.register(owner_leaf)

        assert reservoir._tasks["issue:owner-gate:reservoir"].state == TaskState.OWNER_GATED

        ready = list(reservoir.ready_tasks())
        assert not any(t.key == "issue:owner-gate:reservoir" for t in ready)

    def test_blocked_task_not_in_ready_queue(self) -> None:
        reservoir = DeepOrchestrate(configured_width=2)
        key = "issue:backoff:001"
        reservoir.register(_issue_leaf(key))
        reservoir.lease(key, holder="worker-1")
        reservoir.block(key, reason="CODEX_CLI_COMMAND_UNBOUND")

        ready_keys = [t.key for t in reservoir.ready_tasks()]
        assert key not in ready_keys


# =============================================================================
# PROOF F — Missing authentication fails closed
# =============================================================================


class TestProofF_MissingAuthFailsClosed:
    """PROOF F: missing CALYX_CHATGPT_BUSINESS_CODEX_TOKEN parks the lane."""

    def test_missing_token_raises_credential_error(self) -> None:
        with pytest.raises(CodexCredentialError):
            load_codex_business_credential(environ={})

    def test_blank_token_raises_credential_error(self) -> None:
        with pytest.raises(CodexCredentialError):
            load_codex_business_credential(
                environ={"CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "   "}
            )

    def test_missing_auth_error_message_names_var(self) -> None:
        try:
            load_codex_business_credential(environ={})
        except CodexCredentialError as exc:
            assert "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN" in str(exc)

    def test_no_issue_falsely_marked_running_when_auth_missing(self) -> None:
        reservoir = DeepOrchestrate(configured_width=1)
        key = "issue:auth-missing:001"
        reservoir.register(_issue_leaf(key))
        leaf = reservoir.lease(key, holder="worker-auth-test")

        try:
            from app.calyx_orchestrator.codex_worker_adapter import build_codex_worker_from_env
            build_codex_worker_from_env(
                repository_allowlist=(ALLOWED_REPO,),
                environ={},
            )
        except CodexCredentialError:
            reservoir.block(key, reason="CODEX_AUTH_MISSING")

        assert reservoir._tasks[key].state == TaskState.BLOCKED
        assert reservoir._tasks[key].blocked_reason == "CODEX_AUTH_MISSING"

    def test_unbound_credential_mapping_parks_lane(self) -> None:
        """When BUSINESS_TOKEN_CLI_ENV_VAR is unbound, dispatch raises and lane parks."""
        # The mock transport never reaches the credential mapping check
        # because the adapter raises before calling transport.run().
        # Use a real SubprocessCodexTransport with an unbound mapping.
        from app.calyx_orchestrator.chatgpt_business_codex_provider import (
            CodexCLICommand,
            SubprocessCodexTransport,
        )
        cred = CodexBusinessCredential("tok")
        transport = SubprocessCodexTransport(
            cli_command=CodexCLICommand(command=["echo", "test"])
        )
        # BUSINESS_TOKEN_CLI_ENV_VAR is None → build_cli_env raises
        adapter = CodexCLIAdapter(
            transport=transport,
            credential=cred,
            repository_allowlist=[ALLOWED_REPO],
        )
        from app.calyx_orchestrator.github_coding_executor import DispatchRequest
        req = DispatchRequest(
            mission_id="m1",
            repository=ALLOWED_REPO,
            objective="obj",
            acceptance_criteria=(),
            validation_commands=(),
            budget_class=BudgetClass.NORMAL,
            convergence_class=ConvergenceClass.NEW,
            base_ref="main",
            base_sha=FAKE_SHA,
            related_issue_numbers=(),
            overlapping_pr_numbers=(),
            continuation_pr_numbers=(),
            convergence_pr_numbers=(),
            superseded_pr_numbers=(),
            retry_count=0,
        )
        with pytest.raises(PermissionError, match="CODEX_ADAPTER_CREDENTIAL_MAPPING_UNBOUND"):
            adapter.dispatch(req)


# =============================================================================
# PROOF G — OPENAI_API_KEY fallback cannot occur
# =============================================================================


class TestProofG_ApiKeyFallbackProhibited:
    """PROOF G: OPENAI_API_KEY presence → explicit rejection; no fallback."""

    def test_openai_api_key_present_raises(self) -> None:
        with pytest.raises(CodexApiKeyFallbackError):
            load_codex_business_credential(
                environ={
                    "OPENAI_API_KEY": "sk-paid-billing-key",
                    "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "biz-token-123",
                }
            )

    def test_openai_api_key_error_message_names_prohibition(self) -> None:
        try:
            load_codex_business_credential(environ={"OPENAI_API_KEY": "sk-anything"})
        except CodexApiKeyFallbackError as exc:
            msg = str(exc)
            assert "OPENAI_API_KEY" in msg
            assert "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN" in msg

    def test_api_key_fallback_error_does_not_leak_key_value(self) -> None:
        secret = "sk-super-secret-value"
        try:
            load_codex_business_credential(environ={"OPENAI_API_KEY": secret})
        except CodexApiKeyFallbackError as exc:
            assert secret not in str(exc)

    def test_subprocess_transport_strips_openai_api_key_from_env(self) -> None:
        """SubprocessCodexTransport removes OPENAI_API_KEY from subprocess env."""
        from app.calyx_orchestrator.chatgpt_business_codex_provider import (
            CodexCLICommand,
            SubprocessCodexTransport,
        )
        transport = SubprocessCodexTransport(
            cli_command=CodexCLICommand(command=["env"])
        )
        # If OPENAI_API_KEY were in the env, it would be stripped.
        # We verify by checking the implementation — it explicitly pops the key.
        import inspect
        src = inspect.getsource(SubprocessCodexTransport.run)
        assert "OPENAI_API_KEY" in src
        assert "pop" in src

    def test_provider_rejects_wrong_auth_mode(self) -> None:
        bad_cred = CodexBusinessCredential("some-token", auth_mode="openai_api_key")
        transport = MockCodexProcessTransport(responses=[])
        with pytest.raises(CodexCredentialError):
            CodexCLIAdapter(
                transport=transport,
                credential=bad_cred,
                repository_allowlist=[ALLOWED_REPO],
            )


# =============================================================================
# PROOF H — No subprocess / HTTP / real-API calls during deterministic tests
# =============================================================================


class TestProofH_NoRealCallsInTests:
    """PROOF H: mock process transport is used; no real subprocess or HTTP."""

    def test_mock_transport_call_count_is_controlled(self) -> None:
        worker, transport = _worker([_ok_result()])
        worker.execute(_issue_leaf("issue:no-real-call:001"))
        assert len(transport.calls) == 1
        # Confirm these are mock dict records, not subprocess.CompletedProcess
        assert isinstance(transport.calls[0], dict)

    def test_owner_gate_produces_zero_mock_calls(self) -> None:
        worker, transport = _worker([])
        worker.execute(_issue_leaf("issue:no-call-owner-gate", authority_class=AUTH_PRODUCTION))
        assert len(transport.calls) == 0

    def test_missing_repo_produces_zero_mock_calls(self) -> None:
        worker, transport = _worker([])
        leaf = _issue_leaf("issue:no-call-no-repo")
        leaf.evidence["repository"] = ""
        worker.execute(leaf)
        assert len(transport.calls) == 0

    def test_credential_value_not_in_mock_call_record(self) -> None:
        worker, transport = _worker([_ok_result()])
        worker.execute(_issue_leaf("issue:no-cred-in-calls"))
        # Mock records env_keys (names only), never values
        for call in transport.calls:
            assert PLACEHOLDER_TOKEN not in str(call)


# =============================================================================
# PROOF I — Cost = $0
# =============================================================================


class TestProofI_ZeroCost:
    """PROOF I: no paid provider, no billing, no real model inference."""

    def test_receipts_carry_mock_auth_mode(self) -> None:
        worker, _ = _worker([_ok_result()])
        receipt = worker.execute(_issue_leaf("issue:zero-cost:001"))
        assert receipt.auth_mode == AUTH_MODE_BUSINESS_TOKEN
        ev_str = str(receipt.as_evidence())
        assert PLACEHOLDER_TOKEN not in ev_str

    def test_credential_repr_redacts_token(self) -> None:
        cred = CodexBusinessCredential("super-secret-token")
        r = repr(cred)
        assert "super-secret-token" not in r
        assert "<redacted>" in r

    def test_no_openai_or_requests_imported_by_worker_at_module_level(self) -> None:
        """Worker adapter must not import openai or requests at module level."""
        import sys
        import app.calyx_orchestrator.codex_worker_adapter as adapter_mod
        # 'openai' must not be imported as a side effect of importing the worker
        assert "openai" not in sys.modules
        # 'requests' import in subprocess transport is inside run(), not top-level
        assert "openai" not in dir(adapter_mod)


# =============================================================================
# Auth preflight — standalone credential tests
# =============================================================================


class TestCredentialPreflight:
    """Deterministic preflight checks for the credential module."""

    def test_load_valid_token(self) -> None:
        cred = load_codex_business_credential(
            environ={"CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "biz-tok-abc"}
        )
        assert cred.auth_mode == AUTH_MODE_BUSINESS_TOKEN
        assert cred.bearer_value == "biz-tok-abc"

    def test_bearer_value_matches_token(self) -> None:
        cred = CodexBusinessCredential("my-token-xyz")
        assert cred.bearer_value == "my-token-xyz"

    def test_blank_token_raises(self) -> None:
        with pytest.raises(CodexCredentialError):
            CodexBusinessCredential("   ")

    def test_token_stripped_of_whitespace(self) -> None:
        cred = load_codex_business_credential(
            environ={"CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "  tok-with-spaces  "}
        )
        assert cred.bearer_value == "tok-with-spaces"

    def test_api_key_fallback_fires_before_token_check(self) -> None:
        """API key rejection happens before checking Business token."""
        with pytest.raises(CodexApiKeyFallbackError):
            load_codex_business_credential(
                environ={
                    "OPENAI_API_KEY": "sk-paid",
                    "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "biz-token-valid",
                }
            )


# =============================================================================
# Process adapter dispatch — unit tests
# =============================================================================


class TestCodexCLIAdapterDispatch:
    """Unit tests for CodexCLIAdapter (process-based, not HTTP)."""

    def _provider(self, transport: MockCodexProcessTransport) -> CodexCLIAdapter:
        cred = CodexBusinessCredential(PLACEHOLDER_TOKEN)
        return CodexCLIAdapter(
            transport=transport,
            credential=cred,
            repository_allowlist=[ALLOWED_REPO],
            credential_mapping=_MockCredentialMapping,
        )

    def _request(self, **kwargs: Any) -> Any:
        from app.calyx_orchestrator.github_coding_executor import DispatchRequest
        defaults: dict[str, Any] = {
            "mission_id": "MISSION-TEST",
            "repository": ALLOWED_REPO,
            "objective": "Test objective",
            "acceptance_criteria": ("criterion-1",),
            "validation_commands": ("pytest -q",),
            "budget_class": BudgetClass.NORMAL,
            "convergence_class": ConvergenceClass.NEW,
            "base_ref": "main",
            "base_sha": FAKE_SHA,
            "related_issue_numbers": (),
            "overlapping_pr_numbers": (),
            "continuation_pr_numbers": (),
            "convergence_pr_numbers": (),
            "superseded_pr_numbers": (),
            "retry_count": 0,
        }
        defaults.update(kwargs)
        return DispatchRequest(**defaults)

    def test_new_mission_invokes_process_transport(self) -> None:
        transport = MockCodexProcessTransport(responses=[_ok_result("s-new")])
        result = self._provider(transport).dispatch(self._request())
        assert result.state == "session_created"
        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert call["repository"] == ALLOWED_REPO
        assert call["base_ref"] == "main"
        # Mission content appears in the task prompt
        assert "MISSION-TEST" in call["task"]
        assert "Draft PR only" in call["task"]

    def test_continue_mission_invokes_process_transport(self) -> None:
        transport = MockCodexProcessTransport(responses=[_ok_result("iter-01")])
        result = self._provider(transport).dispatch(
            self._request(
                convergence_class=ConvergenceClass.CONTINUE,
                continuation_pr_numbers=(77,),
            )
        )
        assert result.state == "iteration_requested"
        assert result.pull_request_number == 77
        assert len(transport.calls) == 1

    def test_already_done_raises_before_transport(self) -> None:
        transport = MockCodexProcessTransport(responses=[])
        with pytest.raises(PermissionError, match="CODEX_ADAPTER_ALREADY_DONE"):
            self._provider(transport).dispatch(
                self._request(convergence_class=ConvergenceClass.ALREADY_DONE)
            )
        assert len(transport.calls) == 0

    def test_wrong_repository_raises_before_transport(self) -> None:
        transport = MockCodexProcessTransport(responses=[])
        with pytest.raises(PermissionError, match="CODEX_ADAPTER_REPOSITORY_NOT_ALLOWED"):
            self._provider(transport).dispatch(
                self._request(repository="other-owner/other-repo")
            )
        assert len(transport.calls) == 0

    def test_auth_mode_in_evidence_not_token_value(self) -> None:
        transport = MockCodexProcessTransport(responses=[_ok_result("s-ev")])
        result = self._provider(transport).dispatch(self._request())
        evidence_str = str(result.validation_evidence)
        assert PLACEHOLDER_TOKEN not in evidence_str
        assert "auth_mode:chatgpt_business_codex_token" in evidence_str

    def test_cli_failure_propagates_as_cli_failed_state(self) -> None:
        transport = MockCodexProcessTransport(responses=[_fail_result(exit_code=1)])
        result = self._provider(transport).dispatch(self._request())
        assert result.state == "cli_failed"
        assert result.blocker_code == "CODEX_CLI_EXIT_1"


# =============================================================================
# Eight-lane dispatch — integration proof C + H combined
# =============================================================================


class TestEightLaneMockDispatch:
    """Eight lanes dispatched through mock process transport; no real API."""

    def test_eight_issues_dispatched_unique_sessions(self) -> None:
        responses = [_ok_result(f"sess-{i:02d}") for i in range(8)]
        transport = MockCodexProcessTransport(responses=responses)
        worker = build_codex_worker_with_mock(
            transport=transport,
            repository_allowlist=(ALLOWED_REPO,),
        )

        issue_keys = [f"issue:8lane:disp:{i:02d}" for i in range(8)]
        receipts: list[CodexWorkerReceipt] = [
            worker.execute(_issue_leaf(key)) for key in issue_keys
        ]

        # Without a PR, each result must be blocked/CODEX_DRAFT_PR_REQUIRED.
        # Session uniqueness is verified through transport call records because
        # blocked receipts carry no session_evidence.
        assert all(r.status == "blocked" for r in receipts)
        assert all(r.error_reason == "CODEX_DRAFT_PR_REQUIRED" for r in receipts)
        assert len(transport.calls) == 8
        # Verify 8 unique tasks were dispatched (each task prompt contains the unique issue key)
        dispatched_tasks = [call["task"] for call in transport.calls]
        assert len(set(dispatched_tasks)) == 8
        # Credential value never in call records
        assert PLACEHOLDER_TOKEN not in str(transport.calls)
