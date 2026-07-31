from __future__ import annotations

import pytest

from harvesters.safety import (
    BudgetExceeded,
    CircuitBreaker,
    CircuitOpen,
    CursorGuard,
    CursorRegression,
    RepeatedPageDetector,
    WorkBudget,
    enforce_gbif_offset,
)


def test_work_budget_caps_requests_records_and_writes():
    budget = WorkBudget(max_runtime_seconds=60, max_requests=1, max_records=1, max_db_writes=1)
    budget.add_requests(1)
    budget.add_records(1)
    budget.add_writes(1)
    with pytest.raises(BudgetExceeded):
        budget.add_requests(1)


def test_circuit_breaker_opens_after_empty_threshold():
    breaker = CircuitBreaker(empty_threshold=2)
    breaker.record_page(is_empty=True)
    assert not breaker.is_open
    breaker.record_page(is_empty=True)
    assert breaker.is_open
    with pytest.raises(CircuitOpen):
        breaker.check()


def test_circuit_breaker_opens_on_total_failure():
    breaker = CircuitBreaker(empty_threshold=10, failure_rate_threshold=1.0)
    breaker.record_page(is_empty=False, failure_rate=1.0, had_attempts=True)
    assert breaker.is_open


def test_cursor_guard_rejects_reset_or_regression():
    guard = CursorGuard()
    assert guard.validate(200) == 200
    with pytest.raises(CursorRegression):
        guard.validate(0)


def test_repeated_page_detector_rejects_identical_page():
    detector = RepeatedPageDetector()
    records = [{"id": 1}, {"id": 2}]
    assert detector.is_repeat(records) is False
    assert detector.is_repeat(records) is True


def test_gbif_offset_ceiling_is_enforced():
    enforce_gbif_offset(99_000, 1_000)
    with pytest.raises(BudgetExceeded):
        enforce_gbif_offset(99_500, 1_000)
