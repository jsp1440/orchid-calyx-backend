"""Tests for runtime.swarm — Swarm Execution Governor.

Covers all 12 policy controls, fail-closed behaviour, ledger recording,
concurrency tracking, kill switch, provider error stop, budget enforcement,
and NO_API_MODE integration.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from runtime.swarm import (
    ExecutionRequest,
    GovernorBlockedError,
    GovernorPolicy,
    GovernorPolicyError,
    SwarmExecutionGovernor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER = "anthropic"
_LANE = "calyx-lane-1"


def _paid_policy(**overrides) -> GovernorPolicy:
    """Minimal valid paid-execution policy."""
    defaults = {
        "paid_execution_enabled": True,
        "provider_allowlist": frozenset({_PROVIDER}),
        "per_run_budget": Decimal("1.00"),
        "daily_budget": Decimal("10.00"),
        "monthly_budget": Decimal("50.00"),
    }
    defaults.update(overrides)
    return GovernorPolicy(**defaults)


def _governor(
    policy: GovernorPolicy | None = None, *, no_api_mode_raw: str = "false"
) -> SwarmExecutionGovernor:
    return SwarmExecutionGovernor(
        policy or _paid_policy(), no_api_mode_raw=no_api_mode_raw
    )


def _req(
    provider: str = _PROVIDER,
    lane: str = _LANE,
    retry_count: int = 0,
    estimated_cost_usd: Decimal | None = Decimal("0.10"),
    issue_task_id: str = "issue-42",
) -> ExecutionRequest:
    return ExecutionRequest(
        issue_task_id=issue_task_id,
        provider=provider,
        worker_lane=lane,
        retry_count=retry_count,
        estimated_cost_usd=estimated_cost_usd,
    )


# ---------------------------------------------------------------------------
# GovernorPolicy construction and validation
# ---------------------------------------------------------------------------


class TestPolicyValidation:
    def test_auto_refill_prohibited(self):
        with pytest.raises(GovernorPolicyError, match="AUTO_REFILL_PROHIBITED"):
            GovernorPolicy(auto_refill=True)

    def test_paid_worker_concurrency_must_be_positive(self):
        with pytest.raises(
            GovernorPolicyError, match="PAID_WORKER_CONCURRENCY_MUST_BE_POSITIVE"
        ):
            GovernorPolicy(paid_worker_concurrency=0)

    def test_paid_worker_concurrency_negative_raises(self):
        with pytest.raises(
            GovernorPolicyError, match="PAID_WORKER_CONCURRENCY_MUST_BE_POSITIVE"
        ):
            GovernorPolicy(paid_worker_concurrency=-1)

    def test_max_retries_must_be_non_negative(self):
        with pytest.raises(
            GovernorPolicyError, match="MAX_RETRIES_MUST_BE_NON_NEGATIVE"
        ):
            GovernorPolicy(max_retries=-1)

    def test_paid_enabled_requires_per_run_budget(self):
        with pytest.raises(GovernorPolicyError, match="PER_RUN_BUDGET_REQUIRED"):
            GovernorPolicy(
                paid_execution_enabled=True,
                provider_allowlist=frozenset({_PROVIDER}),
                daily_budget=Decimal("5.00"),
                monthly_budget=Decimal("20.00"),
            )

    def test_paid_enabled_requires_daily_budget(self):
        with pytest.raises(GovernorPolicyError, match="DAILY_BUDGET_REQUIRED"):
            GovernorPolicy(
                paid_execution_enabled=True,
                provider_allowlist=frozenset({_PROVIDER}),
                per_run_budget=Decimal("1.00"),
                monthly_budget=Decimal("20.00"),
            )

    def test_paid_enabled_requires_monthly_budget(self):
        with pytest.raises(GovernorPolicyError, match="MONTHLY_BUDGET_REQUIRED"):
            GovernorPolicy(
                paid_execution_enabled=True,
                provider_allowlist=frozenset({_PROVIDER}),
                per_run_budget=Decimal("1.00"),
                daily_budget=Decimal("5.00"),
            )

    def test_paid_enabled_requires_provider_allowlist(self):
        with pytest.raises(GovernorPolicyError, match="PROVIDER_ALLOWLIST_REQUIRED"):
            GovernorPolicy(
                paid_execution_enabled=True,
                per_run_budget=Decimal("1.00"),
                daily_budget=Decimal("5.00"),
                monthly_budget=Decimal("20.00"),
            )

    def test_valid_paid_policy_constructs_without_error(self):
        p = _paid_policy()
        assert p.paid_execution_enabled is True
        assert p.auto_refill is False

    def test_budget_accepts_int_and_converts_to_decimal(self):
        p = GovernorPolicy(
            paid_execution_enabled=True,
            provider_allowlist=frozenset({_PROVIDER}),
            per_run_budget=2,  # int, not Decimal
            daily_budget=10,
            monthly_budget=50,
        )
        assert isinstance(p.per_run_budget, Decimal)
        assert p.per_run_budget == Decimal("2")

    def test_default_concurrency_is_1(self):
        assert GovernorPolicy().paid_worker_concurrency == 1

    def test_default_max_retries_is_1(self):
        assert GovernorPolicy().max_retries == 1

    def test_default_stop_on_provider_error_is_true(self):
        assert GovernorPolicy().stop_on_provider_error is True

    def test_default_stop_on_budget_threshold_is_true(self):
        assert GovernorPolicy().stop_on_budget_threshold is True

    def test_default_auto_refill_is_false(self):
        assert GovernorPolicy().auto_refill is False

    def test_default_emergency_kill_switch_is_false(self):
        assert GovernorPolicy().emergency_kill_switch is False

    def test_snapshot_contains_all_twelve_controls(self):
        snap = _paid_policy().snapshot()
        expected_keys = {
            "paid_worker_concurrency",
            "max_retries",
            "stop_on_provider_error",
            "stop_on_budget_threshold",
            "auto_refill",
            "per_run_budget",
            "daily_budget",
            "monthly_budget",
            "emergency_kill_switch",
            "provider_allowlist",
            "provider_priority",
            "paid_execution_enabled",
        }
        assert set(snap.keys()) == expected_keys

    def test_snapshot_auto_refill_is_always_false(self):
        snap = _paid_policy().snapshot()
        assert snap["auto_refill"] is False


# ---------------------------------------------------------------------------
# NO_API_MODE guard
# ---------------------------------------------------------------------------


class TestNoApiModeGuard:
    def test_absent_no_api_mode_blocks(self):
        gov = SwarmExecutionGovernor(_paid_policy(), no_api_mode_raw=None)
        decision = gov.authorize(_req())
        assert not decision.authorized
        assert decision.reason == "BLOCKED_NO_API_MODE"

    def test_true_no_api_mode_blocks(self):
        gov = SwarmExecutionGovernor(_paid_policy(), no_api_mode_raw="true")
        decision = gov.authorize(_req())
        assert not decision.authorized
        assert decision.reason == "BLOCKED_NO_API_MODE"

    def test_false_no_api_mode_does_not_block_on_guard(self):
        gov = _governor()
        decision = gov.authorize(_req())
        assert decision.authorized
        assert decision.reason == "AUTHORIZED"

    def test_disabled_no_api_mode_does_not_block_on_guard(self):
        gov = SwarmExecutionGovernor(_paid_policy(), no_api_mode_raw="disabled")
        decision = gov.authorize(_req())
        assert decision.authorized

    def test_begin_raises_when_no_api_mode_blocks(self):
        gov = SwarmExecutionGovernor(_paid_policy(), no_api_mode_raw=None)
        with pytest.raises(GovernorBlockedError) as exc_info:
            gov.begin(_req())
        assert exc_info.value.reason == "BLOCKED_NO_API_MODE"


# ---------------------------------------------------------------------------
# Emergency kill switch
# ---------------------------------------------------------------------------


class TestEmergencyKillSwitch:
    def test_kill_switch_blocks(self):
        gov = _governor(_paid_policy(emergency_kill_switch=True))
        decision = gov.authorize(_req())
        assert not decision.authorized
        assert decision.reason == "BLOCKED_KILL_SWITCH"

    def test_kill_switch_blocks_even_with_false_no_api_mode(self):
        gov = SwarmExecutionGovernor(
            _paid_policy(emergency_kill_switch=True), no_api_mode_raw="false"
        )
        decision = gov.authorize(_req())
        assert decision.reason == "BLOCKED_KILL_SWITCH"

    def test_no_kill_switch_does_not_block(self):
        gov = _governor(_paid_policy(emergency_kill_switch=False))
        decision = gov.authorize(_req())
        assert decision.authorized

    def test_begin_raises_on_kill_switch(self):
        gov = _governor(_paid_policy(emergency_kill_switch=True))
        with pytest.raises(GovernorBlockedError, match="BLOCKED_KILL_SWITCH"):
            gov.begin(_req())


# ---------------------------------------------------------------------------
# Paid execution disabled
# ---------------------------------------------------------------------------


class TestPaidExecutionDisabled:
    def test_disabled_paid_execution_blocks(self):
        gov = SwarmExecutionGovernor(GovernorPolicy(), no_api_mode_raw="false")
        decision = gov.authorize(_req())
        assert not decision.authorized
        assert decision.reason == "BLOCKED_PAID_EXECUTION_DISABLED"


# ---------------------------------------------------------------------------
# Provider allowlist
# ---------------------------------------------------------------------------


class TestProviderAllowlist:
    def test_provider_not_in_allowlist_blocks(self):
        gov = _governor(_paid_policy(provider_allowlist=frozenset({"anthropic"})))
        decision = gov.authorize(_req(provider="openai"))
        assert not decision.authorized
        assert decision.reason == "BLOCKED_PROVIDER_NOT_ALLOWED"

    def test_provider_in_allowlist_allows(self):
        gov = _governor(_paid_policy(provider_allowlist=frozenset({"anthropic"})))
        decision = gov.authorize(_req(provider="anthropic"))
        assert decision.authorized

    def test_empty_allowlist_blocks_all_providers(self):
        # Empty allowlist is only reachable when paid_execution_enabled=False,
        # but we test the behaviour via direct policy with paid disabled.
        gov = SwarmExecutionGovernor(GovernorPolicy(), no_api_mode_raw="false")
        decision = gov.authorize(_req())
        # Blocked at PAID_EXECUTION_DISABLED before reaching allowlist check
        assert not decision.authorized


# ---------------------------------------------------------------------------
# Provider priority ordering
# ---------------------------------------------------------------------------


class TestProviderPriority:
    def test_priority_order_respected(self):
        p = GovernorPolicy(
            paid_execution_enabled=True,
            provider_allowlist=frozenset({"anthropic", "openai", "gemini"}),
            provider_priority=("gemini", "openai"),
            per_run_budget=Decimal("1.00"),
            daily_budget=Decimal("10.00"),
            monthly_budget=Decimal("50.00"),
        )
        ordered = p.ordered_providers()
        assert ordered[0] == "gemini"
        assert ordered[1] == "openai"
        assert "anthropic" in ordered

    def test_providers_not_in_priority_appended_sorted(self):
        p = GovernorPolicy(
            paid_execution_enabled=True,
            provider_allowlist=frozenset({"anthropic", "openai", "gemini"}),
            provider_priority=("openai",),
            per_run_budget=Decimal("1.00"),
            daily_budget=Decimal("10.00"),
            monthly_budget=Decimal("50.00"),
        )
        ordered = p.ordered_providers()
        assert ordered[0] == "openai"
        tail = ordered[1:]
        assert tail == sorted(tail)

    def test_priority_entry_not_in_allowlist_is_ignored(self):
        p = GovernorPolicy(
            paid_execution_enabled=True,
            provider_allowlist=frozenset({"anthropic"}),
            provider_priority=("mystery-provider", "anthropic"),
            per_run_budget=Decimal("1.00"),
            daily_budget=Decimal("10.00"),
            monthly_budget=Decimal("50.00"),
        )
        ordered = p.ordered_providers()
        assert "mystery-provider" not in ordered
        assert ordered == ["anthropic"]


# ---------------------------------------------------------------------------
# Retry limit
# ---------------------------------------------------------------------------


class TestRetryLimit:
    def test_retry_within_limit_allows(self):
        gov = _governor(_paid_policy(max_retries=2))
        decision = gov.authorize(_req(retry_count=2))
        assert decision.authorized

    def test_retry_exceeding_limit_blocks(self):
        gov = _governor(_paid_policy(max_retries=1))
        decision = gov.authorize(_req(retry_count=2))
        assert not decision.authorized
        assert decision.reason == "BLOCKED_RETRY_LIMIT_EXCEEDED"

    def test_zero_retries_allows_first_attempt(self):
        gov = _governor(_paid_policy(max_retries=0))
        decision = gov.authorize(_req(retry_count=0))
        assert decision.authorized

    def test_zero_retries_blocks_any_retry(self):
        gov = _governor(_paid_policy(max_retries=0))
        decision = gov.authorize(_req(retry_count=1))
        assert decision.reason == "BLOCKED_RETRY_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Concurrency limit
# ---------------------------------------------------------------------------


class TestConcurrencyLimit:
    def test_first_worker_is_authorized(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=1))
        assert gov.authorize(_req()).authorized

    def test_concurrency_limit_blocks_second_worker(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=1))
        gov.begin(_req(issue_task_id="task-1"))
        decision = gov.authorize(_req(issue_task_id="task-2"))
        assert not decision.authorized
        assert decision.reason == "BLOCKED_CONCURRENCY_LIMIT"

    def test_slot_released_after_end(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=1))
        entry_id = gov.begin(_req(issue_task_id="task-1"))
        gov.end(entry_id, succeeded=True, termination_reason="completed")
        # Slot should now be free
        assert gov.authorize(_req(issue_task_id="task-2")).authorized

    def test_active_workers_increments_on_begin(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=3))
        assert gov.active_workers == 0
        gov.begin(_req(issue_task_id="t1"))
        assert gov.active_workers == 1
        gov.begin(_req(issue_task_id="t2"))
        assert gov.active_workers == 2

    def test_active_workers_decrements_on_end(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=3))
        e1 = gov.begin(_req(issue_task_id="t1"))
        e2 = gov.begin(_req(issue_task_id="t2"))
        gov.end(e1, succeeded=True, termination_reason="done")
        assert gov.active_workers == 1
        gov.end(e2, succeeded=True, termination_reason="done")
        assert gov.active_workers == 0

    def test_authorize_does_not_change_active_workers(self):
        gov = _governor()
        gov.authorize(_req())
        gov.authorize(_req())
        assert gov.active_workers == 0

    def test_higher_concurrency_allows_multiple_workers(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=2))
        gov.begin(_req(issue_task_id="t1"))
        assert gov.authorize(_req(issue_task_id="t2")).authorized

    def test_active_workers_never_goes_below_zero(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=2))
        e = gov.begin(_req(issue_task_id="t1"))
        gov.end(e, succeeded=True, termination_reason="done")
        gov.end(e, succeeded=True, termination_reason="done")  # spurious double-end
        assert gov.active_workers == 0


# ---------------------------------------------------------------------------
# Budget controls
# ---------------------------------------------------------------------------


class TestPerRunBudget:
    def test_estimate_within_per_run_budget_allows(self):
        gov = _governor(_paid_policy(per_run_budget=Decimal("1.00")))
        assert gov.authorize(_req(estimated_cost_usd=Decimal("0.99"))).authorized

    def test_estimate_equal_to_per_run_budget_allows(self):
        gov = _governor(_paid_policy(per_run_budget=Decimal("1.00")))
        assert gov.authorize(_req(estimated_cost_usd=Decimal("1.00"))).authorized

    def test_estimate_exceeding_per_run_budget_blocks(self):
        gov = _governor(_paid_policy(per_run_budget=Decimal("1.00")))
        decision = gov.authorize(_req(estimated_cost_usd=Decimal("1.01")))
        assert not decision.authorized
        assert decision.reason == "BLOCKED_PER_RUN_BUDGET_EXCEEDED"


class TestDailyBudget:
    def test_daily_budget_blocks_when_accumulated_spend_exceeds(self):
        gov = _governor(_paid_policy(daily_budget=Decimal("1.00")))
        # Spend 0.90
        e = gov.begin(_req(estimated_cost_usd=Decimal("0.90"), issue_task_id="t1"))
        gov.end(e, succeeded=True, termination_reason="done")
        # Another 0.20 would exceed 1.00
        decision = gov.authorize(
            _req(estimated_cost_usd=Decimal("0.20"), issue_task_id="t2")
        )
        assert not decision.authorized
        assert decision.reason == "BLOCKED_DAILY_BUDGET_EXCEEDED"

    def test_daily_budget_allows_when_within(self):
        gov = _governor(_paid_policy(daily_budget=Decimal("1.00")))
        e = gov.begin(_req(estimated_cost_usd=Decimal("0.50"), issue_task_id="t1"))
        gov.end(e, succeeded=True, termination_reason="done")
        assert gov.authorize(
            _req(estimated_cost_usd=Decimal("0.49"), issue_task_id="t2")
        ).authorized

    def test_in_flight_entry_counted_in_daily_budget(self):
        gov = _governor(
            _paid_policy(daily_budget=Decimal("1.00"), paid_worker_concurrency=2)
        )
        gov.begin(
            _req(estimated_cost_usd=Decimal("0.90"), issue_task_id="t1")
        )  # not ended
        decision = gov.authorize(
            _req(estimated_cost_usd=Decimal("0.20"), issue_task_id="t2")
        )
        assert decision.reason == "BLOCKED_DAILY_BUDGET_EXCEEDED"


class TestMonthlyBudget:
    def test_monthly_budget_blocks_when_accumulated_spend_exceeds(self):
        gov = _governor(_paid_policy(monthly_budget=Decimal("1.00")))
        e = gov.begin(_req(estimated_cost_usd=Decimal("0.90"), issue_task_id="t1"))
        gov.end(e, succeeded=True, termination_reason="done")
        decision = gov.authorize(
            _req(estimated_cost_usd=Decimal("0.20"), issue_task_id="t2")
        )
        assert not decision.authorized
        assert decision.reason == "BLOCKED_MONTHLY_BUDGET_EXCEEDED"

    def test_monthly_budget_allows_when_within(self):
        gov = _governor(_paid_policy(monthly_budget=Decimal("1.00")))
        e = gov.begin(_req(estimated_cost_usd=Decimal("0.30"), issue_task_id="t1"))
        gov.end(e, succeeded=True, termination_reason="done")
        assert gov.authorize(
            _req(estimated_cost_usd=Decimal("0.30"), issue_task_id="t2")
        ).authorized

    def test_budget_checks_skipped_when_stop_on_budget_threshold_false(self):
        gov = _governor(
            _paid_policy(
                per_run_budget=Decimal("0.01"),
                daily_budget=Decimal("0.01"),
                monthly_budget=Decimal("0.01"),
                stop_on_budget_threshold=False,
            )
        )
        # Estimate grossly exceeds all budgets — but threshold stop is off
        decision = gov.authorize(_req(estimated_cost_usd=Decimal("999.00")))
        assert decision.authorized

    def test_no_estimated_cost_does_not_trigger_budget_block(self):
        gov = _governor(_paid_policy(per_run_budget=Decimal("0.01")))
        # No estimated cost → treated as 0, within any positive budget
        decision = gov.authorize(_req(estimated_cost_usd=None))
        assert decision.authorized


# ---------------------------------------------------------------------------
# Provider error stop
# ---------------------------------------------------------------------------


class TestProviderErrorStop:
    def test_failed_end_engages_stop(self):
        gov = _governor(_paid_policy(stop_on_provider_error=True))
        e = gov.begin(_req(issue_task_id="t1"))
        gov.end(e, succeeded=False, termination_reason="provider_error")
        decision = gov.authorize(_req(issue_task_id="t2"))
        assert not decision.authorized
        assert decision.reason == "BLOCKED_PROVIDER_ERROR_STOP"

    def test_reset_clears_provider_error_stop(self):
        gov = _governor(_paid_policy(stop_on_provider_error=True))
        e = gov.begin(_req(issue_task_id="t1"))
        gov.end(e, succeeded=False, termination_reason="provider_error")
        gov.reset_provider_error_stop()
        assert gov.authorize(_req(issue_task_id="t2")).authorized

    def test_stop_on_provider_error_false_does_not_engage(self):
        gov = _governor(_paid_policy(stop_on_provider_error=False))
        e = gov.begin(_req(issue_task_id="t1"))
        gov.end(e, succeeded=False, termination_reason="provider_error")
        assert gov.authorize(_req(issue_task_id="t2")).authorized

    def test_notify_provider_error_engages_stop(self):
        gov = _governor(_paid_policy(stop_on_provider_error=True))
        gov.notify_provider_error()
        assert gov.authorize(_req()).reason == "BLOCKED_PROVIDER_ERROR_STOP"

    def test_notify_provider_error_no_op_when_policy_disabled(self):
        gov = _governor(_paid_policy(stop_on_provider_error=False))
        gov.notify_provider_error()
        assert gov.authorize(_req()).authorized


# ---------------------------------------------------------------------------
# Ledger recording
# ---------------------------------------------------------------------------


class TestLedgerRecording:
    def test_begin_creates_ledger_entry(self):
        gov = _governor()
        entry_id = gov.begin(_req(issue_task_id="issue-99"))
        entries = gov.ledger.all()
        assert len(entries) == 1
        assert entries[0].entry_id == entry_id
        assert entries[0].issue_task_id == "issue-99"

    def test_ledger_entry_has_correct_provider_and_lane(self):
        gov = _governor(_paid_policy(provider_allowlist=frozenset({"anthropic"})))
        gov.begin(_req(provider="anthropic", lane="lane-x"))
        entry = gov.ledger.all()[0]
        assert entry.provider == "anthropic"
        assert entry.worker_lane == "lane-x"

    def test_ledger_entry_started_at_is_set(self):
        gov = _governor()
        gov.begin(_req())
        entry = gov.ledger.all()[0]
        assert entry.started_at is not None
        assert entry.started_at.tzinfo is not None

    def test_ledger_entry_initially_in_flight(self):
        gov = _governor()
        gov.begin(_req())
        entry = gov.ledger.all()[0]
        assert entry.succeeded is None
        assert entry.ended_at is None
        assert entry.termination_reason is None

    def test_ledger_entry_finalized_on_end(self):
        gov = _governor()
        entry_id = gov.begin(_req())
        gov.end(
            entry_id,
            succeeded=True,
            termination_reason="completed",
            estimated_tokens=1200,
        )
        entry = gov.ledger.get(entry_id)
        assert entry.succeeded is True
        assert entry.ended_at is not None
        assert entry.termination_reason == "completed"
        assert entry.estimated_tokens == 1200

    def test_ledger_entry_failed_on_end(self):
        gov = _governor()
        entry_id = gov.begin(_req())
        gov.end(entry_id, succeeded=False, termination_reason="timeout")
        entry = gov.ledger.get(entry_id)
        assert entry.succeeded is False
        assert entry.termination_reason == "timeout"

    def test_ledger_policy_snapshot_captured_at_begin(self):
        policy = _paid_policy()
        gov = _governor(policy)
        entry_id = gov.begin(_req())
        entry = gov.ledger.get(entry_id)
        expected_snap = policy.snapshot()
        assert entry.governing_policy_snapshot == expected_snap

    def test_ledger_cost_captured_from_request(self):
        gov = _governor()
        entry_id = gov.begin(_req(estimated_cost_usd=Decimal("0.42")))
        entry = gov.ledger.get(entry_id)
        assert entry.estimated_cost_usd == Decimal("0.42")

    def test_ledger_retry_count_recorded(self):
        gov = _governor()
        entry_id = gov.begin(_req(retry_count=1))
        entry = gov.ledger.get(entry_id)
        assert entry.retry_count == 1

    def test_multiple_entries_accumulated(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=3))
        id1 = gov.begin(_req(issue_task_id="t1"))
        id2 = gov.begin(_req(issue_task_id="t2"))
        gov.end(id1, succeeded=True, termination_reason="done")
        id3 = gov.begin(_req(issue_task_id="t3"))
        assert len(gov.ledger.all()) == 3
        assert {e.entry_id for e in gov.ledger.all()} == {id1, id2, id3}


# ---------------------------------------------------------------------------
# begin() failure path
# ---------------------------------------------------------------------------


class TestBeginBlocked:
    def test_begin_raises_governor_blocked_error_with_reason(self):
        gov = _governor(_paid_policy(emergency_kill_switch=True))
        with pytest.raises(GovernorBlockedError) as exc_info:
            gov.begin(_req())
        assert exc_info.value.reason == "BLOCKED_KILL_SWITCH"

    def test_begin_blocked_does_not_create_ledger_entry(self):
        gov = _governor(_paid_policy(emergency_kill_switch=True))
        try:
            gov.begin(_req())
        except GovernorBlockedError:
            pass
        assert gov.ledger.all() == []

    def test_begin_blocked_does_not_increment_active_workers(self):
        gov = _governor(_paid_policy(emergency_kill_switch=True))
        try:
            gov.begin(_req())
        except GovernorBlockedError:
            pass
        assert gov.active_workers == 0


# ---------------------------------------------------------------------------
# GovernorDecision fields
# ---------------------------------------------------------------------------


class TestGovernorDecision:
    def test_authorized_decision_includes_provider(self):
        gov = _governor()
        decision = gov.authorize(_req(provider=_PROVIDER))
        assert decision.provider == _PROVIDER

    def test_blocked_decision_has_authorized_false(self):
        gov = SwarmExecutionGovernor(_paid_policy(), no_api_mode_raw=None)
        decision = gov.authorize(_req())
        assert decision.authorized is False

    def test_decision_reports_active_workers(self):
        gov = _governor(_paid_policy(paid_worker_concurrency=3))
        gov.begin(_req(issue_task_id="t1"))
        decision = gov.authorize(_req(issue_task_id="t2"))
        assert decision.active_workers == 1
