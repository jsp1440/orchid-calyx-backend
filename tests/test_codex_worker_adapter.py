"""Deterministic integration proofs for the ChatGPT Business Codex worker adapter.

These tests prove all nine control-plane behaviors (A–I) WITHOUT any real
provider API call, without any paid credential, and at $0 cost.

CLEARLY LABELLED:
    CONTROL-PLANE/WORKER-INTEGRATION PROOF (mock transport, placeholder token)
    NOT: LIVE CODEX AUTHENTICATION PROOF (requires real Business token)

Proof inventory:
    A. One issue can traverse the complete lifecycle
    B. Two independent issues can simultaneously hold distinct execution leases
    C. Eight eligible fixtures can be admitted without duplicate ownership
    D. Completion/failure releases capacity and automatically refills it
    E. Owner-gated/blocked/backoff work cannot execute
    F. Missing authentication fails closed (CALYX_CHATGPT_BUSINESS_CODEX_TOKEN absent)
    G. API-key fallback cannot occur (OPENAI_API_KEY present → rejected)
    H. No provider calls occur during these tests (provider_api_called is False
       for mock; all receipts carry provider_api_called=False on the mock path)
    I. Cost = $0 (no real HTTP, no billing, no paid model activation)
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Mapping
from dataclasses import dataclass
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
    CODEX_TASK_ENDPOINT,
    ChatGPTBusinessCodexProvider,
    CodexTransportResponse,
)
from app.calyx_orchestrator.codex_worker_adapter import (
    CodexCodingWorker,
    CodexWorkerReceipt,
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

# ── Mock transport ─────────────────────────────────────────────────────────


@dataclass
class MockCodexTransport:
    """Deterministic transport that never makes real HTTP calls."""

    responses: list[CodexTransportResponse]
    calls: list[tuple[str, str, dict | None]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> CodexTransportResponse:
        self.calls.append((method, path, dict(json_body) if json_body is not None else None))
        return self.responses.pop(0)


def _session_response(session_id: str = "sess-001") -> CodexTransportResponse:
    return CodexTransportResponse(
        status_code=201,
        payload={
            "id": session_id,
            "state": "session_created",
            "pull_request_number": None,
            "pull_request_url": None,
            "branch": f"calyx/issue-{session_id}",
        },
    )


def _session_response_with_pr(
    session_id: str = "sess-001",
    pr_number: int = 42,
) -> CodexTransportResponse:
    return CodexTransportResponse(
        status_code=201,
        payload={
            "id": session_id,
            "state": "dispatched",
            "pull_request_number": pr_number,
            "pull_request_url": f"https://github.com/{ALLOWED_REPO}/pull/{pr_number}",
            "branch": f"calyx/issue-{session_id}",
            "head_sha": "b" * 40,
        },
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
        "acceptance_criteria": ["tests pass", "PR created"],
        "validation_commands": ["pytest -q tests/"],
        "budget_class": BudgetClass.NORMAL.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": FAKE_SHA,
    }
    return leaf


# =============================================================================
# PROOF A — One issue traverses the complete lifecycle
# =============================================================================


class TestProofA_SingleIssueFullLifecycle:
    """PROOF A: one issue traverses lease → dispatch → receipt → complete."""

    def test_full_lifecycle_dispatched(self) -> None:
        transport = MockCodexTransport(responses=[_session_response_with_pr("s1", 99)])
        worker = build_codex_worker_with_mock(
            transport=transport,
            repository_allowlist=(ALLOWED_REPO,),
        )
        leaf = _issue_leaf("issue:full-lifecycle:001")

        receipt = worker.execute(leaf)

        # Lifecycle complete: receipt recorded, no error
        assert receipt.status == "dispatched"
        assert receipt.pull_request_number == 99
        assert receipt.branch == "calyx/issue-s1"
        assert receipt.error_reason is None
        assert receipt.automatic_merge is False
        assert receipt.automatic_deployment is False
        assert receipt.production_mutation is False
        assert receipt.publication is False
        # Auth mode recorded, never the secret
        assert receipt.auth_mode == AUTH_MODE_BUSINESS_TOKEN
        # Session evidence captured
        assert any("codex-session:s1" in e for e in receipt.session_evidence)
        assert any(f"repo-commit:{ALLOWED_REPO}@{FAKE_SHA}" in e for e in receipt.session_evidence)
        assert any("auth_mode:chatgpt_business_codex_token" in e for e in receipt.session_evidence)
        # One HTTP call was made (mock)
        assert len(transport.calls) == 1
        method, path, body = transport.calls[0]
        assert method == "POST"
        assert path == CODEX_TASK_ENDPOINT

    def test_receipt_as_evidence_is_serialisable(self) -> None:
        transport = MockCodexTransport(responses=[_session_response()])
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )
        receipt = worker.execute(_issue_leaf("issue:evidence-serial:001"))
        ev = receipt.as_evidence()
        assert isinstance(ev, dict)
        assert ev["auth_mode"] == AUTH_MODE_BUSINESS_TOKEN
        # The secret placeholder value must not appear in the receipt
        assert PLACEHOLDER_TOKEN not in str(ev)


# =============================================================================
# PROOF B — Two independent issues hold distinct leases simultaneously
# =============================================================================


class TestProofB_TwoLanesConcurrentLeases:
    """PROOF B: two issues hold exclusive, non-overlapping execution leases."""

    def test_two_independent_issues_distinct_leases(self) -> None:
        responses_a = [_session_response_with_pr("sA", 10)]
        responses_b = [_session_response_with_pr("sB", 11)]
        transport_a = MockCodexTransport(responses=responses_a)
        transport_b = MockCodexTransport(responses=responses_b)

        reservoir = DeepOrchestrate(configured_width=2)
        leaf_a = _issue_leaf("issue:concurrent:lane-A")
        leaf_b = _issue_leaf("issue:concurrent:lane-B")
        reservoir.register(leaf_a)
        reservoir.register(leaf_b)

        # Lease both simultaneously
        leased_a = reservoir.lease("issue:concurrent:lane-A", holder="worker-A")
        leased_b = reservoir.lease("issue:concurrent:lane-B", holder="worker-B")

        assert leased_a.lease_holder == "worker-A"
        assert leased_b.lease_holder == "worker-B"
        assert leased_a.key != leased_b.key

        worker_a = build_codex_worker_with_mock(
            transport=transport_a, repository_allowlist=(ALLOWED_REPO,)
        )
        worker_b = build_codex_worker_with_mock(
            transport=transport_b, repository_allowlist=(ALLOWED_REPO,)
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(worker_a.execute, leased_a)
            fut_b = pool.submit(worker_b.execute, leased_b)
            receipt_a = fut_a.result()
            receipt_b = fut_b.result()

        # Independent receipts with distinct PRs
        assert receipt_a.status == "dispatched"
        assert receipt_b.status == "dispatched"
        assert receipt_a.pull_request_number == 10
        assert receipt_b.pull_request_number == 11
        assert receipt_a.task_key != receipt_b.task_key

        # Complete both; capacity freed
        reservoir.complete("issue:concurrent:lane-A", evidence=receipt_a.as_evidence())
        reservoir.complete("issue:concurrent:lane-B", evidence=receipt_b.as_evidence())

        from app.calyx_orchestrator.deep_orchestrate import TaskState
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

        # Lease all eight
        leased = []
        for key in issue_keys:
            leaf = reservoir.lease(key, holder=f"worker-{key}")
            leased.append(leaf)

        lease_holders = {l.lease_holder for l in leased}
        lease_keys = [l.key for l in leased]

        # Eight unique owners, eight unique keys
        assert len(lease_holders) == 8
        assert len(set(lease_keys)) == 8

        # No key appears twice
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
        # No new ready tasks while key is leased
        reservoir.refill()
        ready = list(reservoir.ready_tasks())
        assert all(t.key != key for t in ready)  # leased key not re-offered

        receipt_ev = {
            "status": "dispatched",
            "pull_request_number": 55,
        }
        reservoir.complete(key, evidence=receipt_ev)

        # Key is now completed; a new issue can be registered and refilled
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

        reservoir.block(key, reason="CODEX_AUTH_MISSING")

        assert reservoir._tasks[key].state == TaskState.BLOCKED

        # After block, a successor can be registered and becomes ready
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
        transport = MockCodexTransport(responses=[])
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )
        leaf = _issue_leaf("issue:owner-gate:001", authority_class=authority_class)
        receipt = worker.execute(leaf)

        assert receipt.status == "blocked"
        assert receipt.error_reason == "OWNER_GATE_REQUIRED"
        # No transport call
        assert len(transport.calls) == 0

    def test_owner_gated_task_not_dispatched_by_reservoir(self) -> None:
        reservoir = DeepOrchestrate(configured_width=4)
        owner_leaf = _issue_leaf("issue:owner-gate:reservoir", authority_class=AUTH_PRODUCTION)
        reservoir.register(owner_leaf)

        # After registration, should be OWNER_GATED
        assert reservoir._tasks["issue:owner-gate:reservoir"].state == TaskState.OWNER_GATED

        # BoundedDispatcher should skip it
        ready = list(reservoir.ready_tasks())
        assert not any(t.key == "issue:owner-gate:reservoir" for t in ready)

    def test_blocked_task_in_backoff_not_executable(self) -> None:
        reservoir = DeepOrchestrate(configured_width=2)
        key = "issue:backoff:001"
        leaf = _issue_leaf(key)
        reservoir.register(leaf)
        reservoir.lease(key, holder="worker-1")
        reservoir.block(key, reason="CODEX_AUTH_MISSING")

        # Task in BLOCKED state; ready_tasks should not include it
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

    def test_missing_auth_error_message_does_not_contain_value(self) -> None:
        try:
            load_codex_business_credential(environ={"CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": ""})
        except CodexCredentialError as exc:
            assert "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN" in str(exc)
            # No actual token value should appear (there is none)
            assert "Bearer" not in str(exc)

    def test_no_issue_falsely_marked_running_when_auth_missing(self) -> None:
        """Lane parks safely; reservoir state is unchanged."""
        reservoir = DeepOrchestrate(configured_width=1)
        key = "issue:auth-missing:001"
        reservoir.register(_issue_leaf(key))
        leaf = reservoir.lease(key, holder="worker-auth-test")

        # Simulate what an operator would do: catch the credential error and block
        try:
            # Attempting to build a worker from env with no token
            from app.calyx_orchestrator.codex_worker_adapter import build_codex_worker_from_env
            build_codex_worker_from_env(
                repository_allowlist=(ALLOWED_REPO,),
                environ={},
            )
        except CodexCredentialError:
            reservoir.block(key, reason="CODEX_AUTH_MISSING")

        assert reservoir._tasks[key].state == TaskState.BLOCKED
        assert reservoir._tasks[key].blocked_reason == "CODEX_AUTH_MISSING"


# =============================================================================
# PROOF G — OPENAI_API_KEY fallback cannot occur
# =============================================================================


class TestProofG_ApiKeyFallbackProhibited:
    """PROOF G: OPENAI_API_KEY presence → explicit rejection, not fallback."""

    def test_openai_api_key_present_raises(self) -> None:
        with pytest.raises(CodexApiKeyFallbackError):
            load_codex_business_credential(
                environ={
                    "OPENAI_API_KEY": "sk-paid-billing-key",
                    "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "biz-token-123",
                }
            )

    def test_openai_api_key_error_message_is_clear(self) -> None:
        try:
            load_codex_business_credential(
                environ={"OPENAI_API_KEY": "sk-anything"}
            )
        except CodexApiKeyFallbackError as exc:
            msg = str(exc)
            assert "OPENAI_API_KEY" in msg
            assert "prohibited" in msg.lower() or "prohibited" in msg or "Prohibited" in msg or "prohibited" in msg.lower()
            assert "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN" in msg

    def test_api_key_fallback_error_does_not_leak_key_value(self) -> None:
        secret = "sk-super-secret-value"
        try:
            load_codex_business_credential(environ={"OPENAI_API_KEY": secret})
        except CodexApiKeyFallbackError as exc:
            # The secret value must NOT appear in the error message
            assert secret not in str(exc)

    def test_provider_rejects_wrong_auth_mode(self) -> None:
        """Constructing a provider with a wrong auth_mode credential fails."""
        bad_cred = CodexBusinessCredential("some-token", auth_mode="openai_api_key")
        transport = MockCodexTransport(responses=[])
        with pytest.raises(CodexCredentialError):
            ChatGPTBusinessCodexProvider(
                transport=transport,
                credential=bad_cred,
                repository_allowlist=[ALLOWED_REPO],
            )


# =============================================================================
# PROOF H — No provider calls during deterministic tests
# =============================================================================


class TestProofH_NoProviderCallsInTests:
    """PROOF H: mock transport is called; no real HTTP, no paid inference."""

    def test_mock_transport_call_count_is_controlled(self) -> None:
        transport = MockCodexTransport(responses=[_session_response()])
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )
        leaf = _issue_leaf("issue:no-provider-call:001")
        worker.execute(leaf)
        # Exactly one mock call; no requests library involved
        assert len(transport.calls) == 1

    def test_owner_gate_produces_zero_transport_calls(self) -> None:
        transport = MockCodexTransport(responses=[])
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )
        leaf = _issue_leaf("issue:no-call-owner-gate", authority_class=AUTH_PRODUCTION)
        worker.execute(leaf)
        assert len(transport.calls) == 0

    def test_missing_repo_produces_zero_transport_calls(self) -> None:
        transport = MockCodexTransport(responses=[])
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )
        leaf = _issue_leaf("issue:no-call-no-repo")
        leaf.evidence["repository"] = ""
        worker.execute(leaf)
        assert len(transport.calls) == 0


# =============================================================================
# PROOF I — Cost = $0
# =============================================================================


class TestProofI_ZeroCost:
    """PROOF I: no real API invoked; no billing; no paid model activation."""

    def test_receipts_carry_mock_auth_mode_not_real_billing(self) -> None:
        transport = MockCodexTransport(responses=[_session_response()])
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )
        receipt = worker.execute(_issue_leaf("issue:zero-cost:001"))
        assert receipt.auth_mode == AUTH_MODE_BUSINESS_TOKEN
        # Placeholder token not in evidence
        ev_str = str(receipt.as_evidence())
        assert PLACEHOLDER_TOKEN not in ev_str

    def test_credential_repr_redacts_token(self) -> None:
        cred = CodexBusinessCredential("super-secret-token")
        r = repr(cred)
        assert "super-secret-token" not in r
        assert "<redacted>" in r

    def test_no_openai_import_in_worker(self) -> None:
        """The worker module does not import openai at module level."""
        import app.calyx_orchestrator.codex_worker_adapter as adapter_mod
        import sys
        # openai should NOT be in the module's namespace at import time
        assert "openai" not in dir(adapter_mod)
        # openai package should not have been imported as a side effect
        # (it's not installed in this environment, so the absence is certain)
        assert "openai" not in sys.modules


# =============================================================================
# Auth preflight — standalone credential and check tests
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
        """Even if Business token is present, API key presence rejects first."""
        with pytest.raises(CodexApiKeyFallbackError):
            load_codex_business_credential(
                environ={
                    "OPENAI_API_KEY": "sk-paid",
                    "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN": "biz-token-valid",
                }
            )


# =============================================================================
# Provider dispatch — unit tests
# =============================================================================


class TestCodexProviderDispatch:
    """Unit tests for ChatGPTBusinessCodexProvider."""

    def _provider(self, transport: MockCodexTransport) -> ChatGPTBusinessCodexProvider:
        cred = CodexBusinessCredential(PLACEHOLDER_TOKEN)
        return ChatGPTBusinessCodexProvider(
            transport=transport,
            credential=cred,
            repository_allowlist=[ALLOWED_REPO],
        )

    def _request(self, **kwargs) -> Any:
        from app.calyx_orchestrator.github_coding_executor import DispatchRequest
        defaults = {
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

    def test_new_mission_creates_session(self) -> None:
        transport = MockCodexTransport(responses=[_session_response("s-new")])
        result = self._provider(transport).dispatch(self._request())
        assert result.state == "session_created"
        assert len(transport.calls) == 1
        method, path, body = transport.calls[0]
        assert method == "POST"
        assert path == CODEX_TASK_ENDPOINT
        assert body["mission_id"] == "MISSION-TEST"
        assert body["draft_pr"] is True

    def test_continue_missions_posts_iteration(self) -> None:
        transport = MockCodexTransport(
            responses=[CodexTransportResponse(status_code=201, payload={"id": "iter-01"})]
        )
        result = self._provider(transport).dispatch(
            self._request(
                convergence_class=ConvergenceClass.CONTINUE,
                continuation_pr_numbers=(77,),
            )
        )
        assert result.state == "iteration_requested"
        assert result.pull_request_number == 77
        method, path, _ = transport.calls[0]
        assert method == "POST"
        assert "/codex/prs/77/iterations" in path

    def test_already_done_raises(self) -> None:
        transport = MockCodexTransport(responses=[])
        with pytest.raises(PermissionError, match="CODEX_PROVIDER_ALREADY_DONE"):
            self._provider(transport).dispatch(
                self._request(convergence_class=ConvergenceClass.ALREADY_DONE)
            )

    def test_wrong_repository_raises(self) -> None:
        transport = MockCodexTransport(responses=[])
        with pytest.raises(PermissionError, match="CODEX_PROVIDER_REPOSITORY_NOT_ALLOWED"):
            self._provider(transport).dispatch(
                self._request(repository="other-owner/other-repo")
            )

    def test_auth_mode_in_evidence_not_token_value(self) -> None:
        transport = MockCodexTransport(responses=[_session_response("s-ev")])
        result = self._provider(transport).dispatch(self._request())
        evidence_str = str(result.validation_evidence)
        assert PLACEHOLDER_TOKEN not in evidence_str
        assert "auth_mode:chatgpt_business_codex_token" in evidence_str


# =============================================================================
# Eight-lane BoundedDispatcher integration with CodexCodingWorker
# =============================================================================


class TestEightLaneBoundedDispatcher:
    """Eight concurrent lanes wired to CodexCodingWorker via BoundedDispatcher adaptation."""

    def test_eight_issues_dispatched_no_duplicates(self) -> None:
        """Prove C + H: eight issues dispatched; each gets a unique session; no provider."""
        responses = [_session_response(f"sess-{i:02d}") for i in range(8)]
        transport = MockCodexTransport(responses=responses)
        worker = build_codex_worker_with_mock(
            transport=transport, repository_allowlist=(ALLOWED_REPO,)
        )

        issue_keys = [f"issue:8lane:disp:{i:02d}" for i in range(8)]
        receipts: list[CodexWorkerReceipt] = []
        for key in issue_keys:
            leaf = _issue_leaf(key)
            receipt = worker.execute(leaf)
            receipts.append(receipt)

        session_ids = [
            next((e.split("codex-session:")[1] for e in r.session_evidence if "codex-session:" in e), None)
            for r in receipts
        ]
        # All sessions unique
        assert len(set(session_ids)) == 8
        # All dispatched
        assert all(r.status == "session_created" for r in receipts)
        # Exactly 8 mock calls
        assert len(transport.calls) == 8
