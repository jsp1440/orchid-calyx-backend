"""Stable fingerprints for governed budget blockers."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _period(reason: str, now: datetime) -> tuple[str, str]:
    upper = reason.upper()
    if "MONTHLY" in upper:
        return "month", now.strftime("%Y-%m")
    if "DAILY" in upper:
        return "day", now.strftime("%Y-%m-%d")
    return "policy", "static"


def budget_blocker_fingerprint(
    reason: str,
    *,
    provider: str = "",
    allowlist: str = "",
    estimated_cost: str = "",
    per_run_budget: str = "",
    daily_budget: str = "",
    monthly_budget: str = "",
    now: datetime | None = None,
) -> str:
    """Return a deterministic, non-secret identity for a budget condition."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    period_name, period = _period(reason, current)
    upper = reason.upper()
    condition: dict[str, Any] = {
        "schema": "oc.budget-blocker.v1",
        "reason": upper,
        "provider": provider.strip().lower(),
        "allowlist": sorted(
            {item.strip().lower() for item in allowlist.split(",") if item.strip()}
        ),
        "estimated_cost": estimated_cost.strip(),
        "period_name": period_name,
        "period": period,
    }
    if "MONTHLY" in upper:
        condition["monthly_budget"] = monthly_budget.strip()
    elif "DAILY" in upper:
        condition["daily_budget"] = daily_budget.strip()
    elif "PER_RUN" in upper:
        condition["per_run_budget"] = per_run_budget.strip()
    else:
        condition.update(
            {
                "per_run_budget": per_run_budget.strip(),
                "daily_budget": daily_budget.strip(),
                "monthly_budget": monthly_budget.strip(),
            }
        )
    canonical = json.dumps(condition, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def fingerprint_from_environment(reason: str, *, now: datetime | None = None) -> str:
    """Build a blocker fingerprint from the governor's non-secret inputs."""
    return budget_blocker_fingerprint(
        reason,
        provider=_env("OC_GOVERNOR_PROVIDER"),
        allowlist=_env("OC_GOVERNOR_PROVIDER_ALLOWLIST"),
        estimated_cost=_env("OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD"),
        per_run_budget=_env("OC_GOVERNOR_PER_RUN_BUDGET_USD"),
        daily_budget=_env("OC_GOVERNOR_DAILY_BUDGET_USD"),
        monthly_budget=_env("OC_GOVERNOR_MONTHLY_BUDGET_USD"),
        now=now,
    )
