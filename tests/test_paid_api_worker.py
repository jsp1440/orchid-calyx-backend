"""Deterministic tests for the paid API budget governor, provider, and worker.

All tests use MockPaidProvider — ZERO real API calls, ZERO actual cost.
The mock confirms reservations via the real BudgetGovernor so all budget
invariants are exercised faithfully.

Proof coverage:
    Budget: pre-reservation, confirmation, release, ceiling enforcement
    Concurrency: 2 and 8 simultaneous lanes, no shared-state corruption
    Authority: owner-gate classes blocked unconditionally
    Retries: max 2 retries; no unbounded loop
    Evidence: receipt contains provider/model/token/cost/ledger-line
    Tier 0: existing no-API path untouched (separate import)
"""

from __future__ import annotations

import concurrent.futures
import threading
from dataclasses import field

import pytest

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
from app.calyx_orchestrator.paid_api_budget_governor import (
    HARD_CEILING_USD,
    BudgetExhaustedError,
    BudgetReservation,
    PaidAPIBudgetGovernor,
)
from app.calyx_orchestrator.paid_api_provider import MockPaidProvider
from app.calyx_orchestrator.paid_api_worker import (
    MAX_RETRIES,
    PaidAPIWorker,
    PaidAPIWorkerReceipt,
    build_paid_api_worker_with_mock,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

ALLOWED_REPO = "jsp1440/orchid-calyx-backend"
FAKE_SHA = "a" * 40


def _leaf(
    key: str,
    authority_class: str = AUTH_WORKSPACE,
) -> TaskLeaf:
    leaf = TaskLeaf(
        key=key,
        title=f"Test: {key}",
        repo="orchid-calyx-backend",
        module="app",
        priority=Priority.P1,
        authority_class=authority_class,
        consequence_risk="low",
    )
    leaf.state = TaskState.READY
    leaf.evidence = {
        "mission_id": key,
        "repository": ALLOWED_REPO,
        "objective": f"Implement {key}",
        "acceptance_criteria": ["tests pass"],
        "validation_commands": ["pytest -q"],
        "budget_class": BudgetClass.TINY.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": FAKE_SHA,
    }
    return leaf


def _worker(
    responses: list[str] | None = None,
) -> tuple[PaidAPIWorker, PaidAPIBudgetGovernor, MockPaidProvider]:
    return build_paid_api_worker_with_mock(responses=responses)


# ── Budget governor tests ─────────────────────────────────────────────────────


class TestBudgetGovernor:
    def test_hard_ceiling_cannot_be_exceeded_on_construction(self) -> None:
        with pytest.raises(ValueError, match="BUDGET_CEILING_EXCEEDS_PROGRAM_LIMIT"):
            PaidAPIBudgetGovernor(ceiling_usd=HARD_CEILING_USD + 0.01)

    def test_zero_ceiling_raises(self) -> None:
        with pytest.raises(ValueError):
            PaidAPIBudgetGovernor(ceiling_usd=0.0)

    def test_reserve_increases_reserved(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=10.0)
        gov.reserve("t1", 1.00)
        assert gov.reserved_usd == pytest.approx(1.00)
        assert gov.spent_usd == 0.0

    def test_confirm_moves_reserved_to_spent(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=10.0)
        rsv = gov.reserve("t1", 1.00)
        gov.confirm(
            rsv.reservation_id,
            actual_usd=0.80,
            run_id="r1",
            provider="test",
            model="m1",
            input_tokens=100,
            output_tokens=50,
        )
        assert gov.spent_usd == pytest.approx(0.80)
        assert gov.reserved_usd == 0.0

    def test_release_removes_reservation_without_spending(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=10.0)
        rsv = gov.reserve("t1", 1.00)
        gov.release_reservation(rsv.reservation_id)
        assert gov.reserved_usd == 0.0
        assert gov.spent_usd == 0.0

    def test_ceiling_enforced_on_reserve(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=1.00)
        gov.reserve("t1", 0.80)
        with pytest.raises(BudgetExhaustedError):
            gov.reserve("t2", 0.30)  # 0.80 + 0.30 > 1.00

    def test_released_reservation_frees_capacity(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=1.00)
        rsv = gov.reserve("t1", 0.80)
        gov.release_reservation(rsv.reservation_id)
        gov.reserve("t2", 0.90)  # should not raise

    def test_no_auto_reload(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=0.10)
        rsv = gov.reserve("t1", 0.05)
        gov.confirm(rsv.reservation_id, actual_usd=0.05, run_id="r1",
                    provider="p", model="m", input_tokens=10, output_tokens=5)
        rsv2 = gov.reserve("t2", 0.04)
        gov.confirm(rsv2.reservation_id, actual_usd=0.04, run_id="r2",
                    provider="p", model="m", input_tokens=10, output_tokens=5)
        with pytest.raises(BudgetExhaustedError):
            gov.reserve("t3", 0.02)  # ceiling exhausted, no reload
        assert gov.spent_usd == pytest.approx(0.09)

    def test_summary_structure(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=5.0)
        s = gov.summary()
        assert s["auto_reload"] is False
        assert s["ceiling_usd"] == 5.0
        assert s["committed_usd"] == 0.0

    def test_thread_safe_concurrent_reservations(self) -> None:
        gov = PaidAPIBudgetGovernor(ceiling_usd=50.0)
        errors: list[Exception] = []
        successful: list[BudgetReservation] = []
        lock = threading.Lock()

        def reserve_and_confirm() -> None:
            try:
                rsv = gov.reserve("t", 0.01)
                gov.confirm(rsv.reservation_id, actual_usd=0.01, run_id="r",
                            provider="p", model="m", input_tokens=10, output_tokens=5)
                with lock:
                    successful.append(rsv)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: reserve_and_confirm(), range(8)))

        assert not errors
        assert len(successful) == 8
        assert gov.spent_usd == pytest.approx(0.08)


# ── Worker integration tests ──────────────────────────────────────────────────


class TestPaidAPIWorkerUnit:
    def test_successful_execution_returns_completed_receipt(self) -> None:
        worker, governor, provider = _worker(["Analysis: implement X by doing Y"])
        receipt = worker.execute(_leaf("issue:paid:001"))
        assert receipt.status == "completed"
        assert receipt.provider == "mock"
        assert receipt.run_id is not None
        assert receipt.input_tokens == provider.mock_input_tokens
        assert receipt.output_tokens == provider.mock_output_tokens
        assert receipt.actual_usd == 0.0
        assert "Analysis:" in receipt.analysis_excerpt

    def test_receipt_contains_ledger_line(self) -> None:
        worker, governor, provider = _worker(["plan"])
        receipt = worker.execute(_leaf("issue:ledger:001"))
        assert receipt.receipt_ledger_line is not None
        assert "[OC-GOVERNOR-COST]" in receipt.receipt_ledger_line
        assert "mock" in receipt.receipt_ledger_line

    def test_receipt_as_evidence_is_serialisable(self) -> None:
        worker, _, _ = _worker()
        receipt = worker.execute(_leaf("issue:serial:001"))
        ev = receipt.as_evidence()
        assert ev["status"] == "completed"
        assert ev["automatic_merge"] is False
        assert ev["production_mutation"] is False

    @pytest.mark.parametrize(
        "authority_class",
        [AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE],
    )
    def test_owner_gate_blocked_zero_provider_calls(self, authority_class: str) -> None:
        worker, _, provider = _worker([])
        receipt = worker.execute(_leaf("issue:gate:001", authority_class=authority_class))
        assert receipt.status == "blocked"
        assert receipt.error_reason == "OWNER_GATE_REQUIRED"
        assert len(provider.calls) == 0

    def test_budget_reserved_before_call(self) -> None:
        """Provider cannot be called unless a reservation exists in the governor."""
        from app.calyx_orchestrator.paid_api_budget_governor import PaidAPIBudgetGovernor

        calls_during: list[float] = []

        class _InspectingMock(MockPaidProvider):
            def call(self, *, governor, reservation, **kwargs):  # type: ignore[override]
                calls_during.append(governor.reserved_usd)
                return super().call(governor=governor, reservation=reservation, **kwargs)

        provider = _InspectingMock(responses=["ok"])
        governor = PaidAPIBudgetGovernor(ceiling_usd=50.0)
        worker = PaidAPIWorker(provider=provider, governor=governor)
        worker.execute(_leaf("issue:prereserve:001"))
        # During the call, reserved_usd was positive (pre-reserved)
        assert all(r > 0 for r in calls_during)

    def test_budget_confirmed_after_call(self) -> None:
        worker, governor, _ = _worker()
        worker.execute(_leaf("issue:confirm:001"))
        assert governor.reserved_usd == 0.0  # reservation consumed
        assert governor.spent_usd == 0.0      # mock cost is $0

    def test_max_retries_not_exceeded(self) -> None:
        """Worker retries at most MAX_RETRIES times on failure."""
        call_count = 0

        class _FailingMock(MockPaidProvider):
            def call(self, *, governor, reservation, **kwargs):  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                governor.release_reservation(reservation.reservation_id)
                raise RuntimeError("simulated failure")

        provider = _FailingMock()
        governor = PaidAPIBudgetGovernor(ceiling_usd=50.0)
        worker = PaidAPIWorker(provider=provider, governor=governor)
        receipt = worker.execute(_leaf("issue:retry:001"))

        assert receipt.status == "failed"
        assert call_count <= MAX_RETRIES

    def test_ceiling_exhaustion_returns_blocked(self) -> None:
        provider = MockPaidProvider(responses=["ok"])
        governor = PaidAPIBudgetGovernor(ceiling_usd=0.001)
        worker = PaidAPIWorker(provider=provider, governor=governor)
        # Pre-exhaust the budget
        try:
            governor.reserve("pre", 0.001)
        except BudgetExhaustedError:
            pass
        else:
            # budget pre-reserved; now worker.execute should fail on reservation
            receipt = worker.execute(_leaf("issue:exhaust:001"))
            assert receipt.status == "blocked"
            assert "BUDGET_EXHAUSTED" in (receipt.error_reason or "")

    def test_auto_merge_deployment_production_always_false(self) -> None:
        worker, _, _ = _worker()
        receipt = worker.execute(_leaf("issue:safety:001"))
        assert receipt.automatic_merge is False
        assert receipt.automatic_deployment is False
        assert receipt.production_mutation is False
        assert receipt.publication is False


# ── Concurrency: 2-lane Stage B proof ────────────────────────────────────────


class TestConcurrentLanes:
    def test_two_lanes_concurrent_unique_run_ids(self) -> None:
        worker, governor, provider = build_paid_api_worker_with_mock(
            responses=["analysis-A", "analysis-B"]
        )
        leaves = [_leaf(f"issue:concurrent:{i}") for i in range(2)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(worker.execute, leaves))

        assert len(receipts) == 2
        assert all(r.status == "completed" for r in receipts)
        run_ids = [r.run_id for r in receipts]
        assert len(set(run_ids)) == 2  # unique run IDs

    def test_two_lanes_independent_task_keys(self) -> None:
        worker, _, _ = build_paid_api_worker_with_mock(responses=["r1", "r2"])
        leaves = [_leaf("issue:lanes:A"), _leaf("issue:lanes:B")]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(worker.execute, leaves))
        task_keys = [r.task_key for r in receipts]
        assert len(set(task_keys)) == 2

    def test_eight_lanes_no_budget_corruption(self) -> None:
        """Eight concurrent reservations must not corrupt the governor's accounting."""
        worker, governor, _ = build_paid_api_worker_with_mock(
            responses=[f"r{i}" for i in range(8)]
        )
        leaves = [_leaf(f"issue:8lane:{i}") for i in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(worker.execute, leaves))

        assert len(receipts) == 8
        assert all(r.status == "completed" for r in receipts)
        # Governor: all reservations released, 8 receipts recorded
        assert governor.reserved_usd == 0.0
        assert len(governor.all_receipts()) == 8

    def test_reservoir_lease_integration(self) -> None:
        """8 leaves admitted to reservoir; each holds exclusive lease during execution."""
        reservoir = DeepOrchestrate(configured_width=8)
        keys = [f"issue:reservoir:{i}" for i in range(8)]
        for k in keys:
            reservoir.register(_leaf(k))

        worker, _, _ = build_paid_api_worker_with_mock(
            responses=[f"r{i}" for i in range(8)]
        )

        def _lease_and_execute(key: str) -> PaidAPIWorkerReceipt:
            leased = reservoir.lease(key, holder=f"paid-worker-{key}")
            receipt = worker.execute(leased)
            if receipt.status == "completed":
                reservoir.complete(key, evidence=receipt.as_evidence())
            else:
                reservoir.block(key, reason=receipt.error_reason or "UNKNOWN")
            return receipt

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(_lease_and_execute, keys))

        assert all(r.status == "completed" for r in receipts)
        for k in keys:
            assert reservoir._tasks[k].state == TaskState.COMPLETED


# ── Provider availability / factory ──────────────────────────────────────────


class TestProviderFactory:
    def test_no_keys_raises_runtime_error(self) -> None:
        from app.calyx_orchestrator.paid_api_provider import build_cheapest_provider_from_env
        with pytest.raises(RuntimeError, match="PAID_API_NO_KEY_CONFIGURED"):
            build_cheapest_provider_from_env(environ={})

    def test_openai_key_preferred_over_anthropic(self) -> None:
        from app.calyx_orchestrator.paid_api_provider import (
            OpenAIPaidProvider,
            build_cheapest_provider_from_env,
        )
        provider = build_cheapest_provider_from_env(
            environ={
                "OPENAI_API_KEY": "sk-test",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            }
        )
        assert isinstance(provider, OpenAIPaidProvider)

    def test_anthropic_used_when_only_anthropic_set(self) -> None:
        from app.calyx_orchestrator.paid_api_provider import (
            AnthropicPaidProvider,
            build_cheapest_provider_from_env,
        )
        provider = build_cheapest_provider_from_env(
            environ={"ANTHROPIC_API_KEY": "sk-ant-test"}
        )
        assert isinstance(provider, AnthropicPaidProvider)

    def test_mock_provider_zero_cost(self) -> None:
        _, governor, provider = build_paid_api_worker_with_mock()
        assert provider.mock_cost_usd == 0.0

    def test_build_paid_api_worker_from_env_no_keys_blocked(self) -> None:
        from app.calyx_orchestrator.paid_api_worker import build_paid_api_worker_from_env
        with pytest.raises(RuntimeError, match="PAID_API_NO_KEY_CONFIGURED"):
            build_paid_api_worker_from_env(environ={})


# ── Separation from Tier 0 / Business subscription path ──────────────────────


class TestTierSeparation:
    def test_paid_api_imports_do_not_reference_codex_credential_in_code(self) -> None:
        """Paid API mode must not use CALYX_CHATGPT_BUSINESS_CODEX_TOKEN at runtime."""
        import ast
        import inspect
        import app.calyx_orchestrator.paid_api_worker as paid_mod
        # Parse AST: the token name must not appear as a string literal or Name node
        src = inspect.getsource(paid_mod)
        tree = ast.parse(src)
        credential = "CALYX_CHATGPT_BUSINESS_CODEX_TOKEN"
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and credential in str(node.value):
                raise AssertionError(
                    f"paid_api_worker contains {credential!r} as a string literal — "
                    "paid path must not reference the Business subscription credential"
                )
            if isinstance(node, ast.Name) and node.id == credential:
                raise AssertionError(
                    f"paid_api_worker references {credential!r} as a Name — "
                    "paid path must not reference the Business subscription credential"
                )

    def test_codex_worker_unchanged(self) -> None:
        """Existing CodexCodingWorker must still be importable unchanged."""
        from app.calyx_orchestrator.codex_worker_adapter import (
            CodexCodingWorker,
            build_codex_worker_with_mock,
        )
        assert CodexCodingWorker is not None

    def test_paid_api_worker_different_worker_id(self) -> None:
        from app.calyx_orchestrator.paid_api_worker import PaidAPIWorker
        from app.calyx_orchestrator.codex_worker_adapter import CODEX_WORKER_ID
        assert PaidAPIWorker.WORKER_ID != CODEX_WORKER_ID
