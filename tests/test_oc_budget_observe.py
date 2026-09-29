from __future__ import annotations

from datetime import datetime, timezone

from scripts.oc_budget_observe import observe_issue, observe_issues


def blocked_issue(number: int = 1401) -> dict:
    return {
        "number": number,
        "title": "Implement provider-backed repair",
        "body": "OC-SWARM-WRITES: control-plane",
        "labels": ["oc-blocked", "oc-p4"],
        "comments": [{"body": "OC-BLOCKED-ON: budget:" + "a" * 24}],
    }


def configure_budget(monkeypatch, *, monthly_spend: str = "9.80") -> None:
    values = {
        "NO_API_MODE": "false",
        "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
        "OC_GOVERNOR_PROVIDER": "anthropic",
        "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
        "OC_GOVERNOR_MAX_RETRIES": "1",
        "OC_GOVERNOR_PER_RUN_BUDGET_USD": "1.00",
        "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
        "OC_GOVERNOR_MONTHLY_BUDGET_USD": "10.00",
        "OC_GOVERNOR_DAILY_SPEND_USD": "1.00",
        "OC_GOVERNOR_MONTHLY_SPEND_USD": monthly_spend,
        "OC_CLAUDE_CHEAP_ESTIMATED_COST_USD": "0.50",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_observation_is_issue_specific_and_reproduces_monthly_denial(monkeypatch):
    configure_budget(monkeypatch)
    first = observe_issues(
        [blocked_issue(1401), blocked_issue(1402)],
        now=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    assert set(first) == {"1401", "1402"}
    assert first["1401"] == first["1402"]


def test_observation_changes_when_budget_condition_clears(monkeypatch):
    configure_budget(monkeypatch, monthly_spend="1.00")
    observed = observe_issue(
        blocked_issue(), now=datetime(2026, 9, 21, tzinfo=timezone.utc)
    )
    assert observed

    configure_budget(monkeypatch, monthly_spend="9.80")
    blocked = observe_issue(
        blocked_issue(), now=datetime(2026, 9, 21, tzinfo=timezone.utc)
    )
    assert blocked
    assert blocked != observed


def test_missing_spend_fails_closed_without_observation(monkeypatch):
    configure_budget(monkeypatch)
    monkeypatch.delenv("OC_GOVERNOR_MONTHLY_SPEND_USD")
    assert observe_issue(blocked_issue()) is None


def test_non_budget_governor_hold_is_not_observed_as_budget_clear(monkeypatch):
    configure_budget(monkeypatch)
    issue = blocked_issue()
    issue["comments"] = [{"body": "OC-BLOCKED-ON: governor:BLOCKED_KILL_SWITCH"}]
    assert observe_issue(issue) is None
