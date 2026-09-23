from __future__ import annotations

from datetime import datetime, timezone

from scripts.oc_budget_blocker import budget_blocker_fingerprint


def test_monthly_budget_fingerprint_is_stable_within_the_same_blocked_period() -> None:
    kwargs = {
        "provider": "anthropic",
        "allowlist": "anthropic",
        "estimated_cost": "2.00",
        "monthly_budget": "10.00",
    }
    first = budget_blocker_fingerprint(
        "BLOCKED_MONTHLY_BUDGET_EXCEEDED",
        now=datetime(2026, 9, 21, tzinfo=timezone.utc),
        **kwargs,
    )
    second = budget_blocker_fingerprint(
        "BLOCKED_MONTHLY_BUDGET_EXCEEDED",
        now=datetime(2026, 9, 28, tzinfo=timezone.utc),
        **kwargs,
    )
    assert first == second


def test_monthly_budget_fingerprint_changes_when_the_relevant_period_or_policy_changes() -> (
    None
):
    base = {
        "reason": "BLOCKED_MONTHLY_BUDGET_EXCEEDED",
        "provider": "anthropic",
        "allowlist": "anthropic",
        "estimated_cost": "2.00",
        "monthly_budget": "10.00",
        "now": datetime(2026, 9, 21, tzinfo=timezone.utc),
    }
    assert budget_blocker_fingerprint(**base) != budget_blocker_fingerprint(
        **{**base, "now": datetime(2026, 10, 1, tzinfo=timezone.utc)}
    )
    assert budget_blocker_fingerprint(**base) != budget_blocker_fingerprint(
        **{**base, "monthly_budget": "20.00"}
    )
