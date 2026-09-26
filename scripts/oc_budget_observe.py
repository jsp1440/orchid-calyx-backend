"""Observe current governed budget conditions without invoking a provider.

The blocked-work reconciler may release a budget-denied issue only when the
same issue's governed condition is observably different. This module computes
that observation from the same deterministic route, policy, and durable spend
inputs used by the completion lane. Missing or malformed inputs produce no
observation, which deliberately keeps the issue parked.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.oc_budget_blocker import budget_blocker_fingerprint
from scripts.oc_model_router import (
    DEFAULT_ESTIMATED_COST_USD,
    TIERS,
    ProviderNotRequired,
    choose_route,
)

BUDGET_REF = re.compile(r"^budget:[a-f0-9]{24}$", re.IGNORECASE)
BLOCKED_ON = re.compile(
    r"^OC-BLOCKED-ON:\s*(?P<ref>\S+)\s*$", re.IGNORECASE | re.MULTILINE
)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _money(name: str) -> Decimal:
    raw = _env(name)
    if not raw:
        raise ValueError(f"missing {name}")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {name}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def _labels(issue: dict[str, Any]) -> list[str]:
    result = []
    for label in issue.get("labels") or []:
        name = label if isinstance(label, str) else label.get("name")
        if name:
            result.append(str(name))
    return result


def _text(issue: dict[str, Any]) -> str:
    parts = [str(issue.get("body") or "")]
    for comment in issue.get("comments") or []:
        if isinstance(comment, dict):
            parts.append(str(comment.get("body") or ""))
        elif isinstance(comment, str):
            parts.append(comment)
    return "\n".join(parts)


def _has_current_budget_marker(issue: dict[str, Any]) -> bool:
    matches = list(BLOCKED_ON.finditer(_text(issue)))
    return bool(matches and BUDGET_REF.fullmatch(matches[-1].group("ref")))


def _authorized_budget_observation(
    issue: dict[str, Any],
) -> tuple[str, str, int, int] | None:
    """Return provider policy inputs only when non-budget gates are clear."""
    if _env("NO_API_MODE").lower() in {"", "true", "1", "yes", "on"}:
        return None
    if _env("OC_GOVERNOR_EMERGENCY_KILL_SWITCH").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }:
        return None
    if _env("OC_GOVERNOR_PAID_EXECUTION_ENABLED").lower() not in {
        "true",
        "1",
        "yes",
        "on",
    }:
        return None
    provider = _env("OC_GOVERNOR_PROVIDER")
    allowlist = _env("OC_GOVERNOR_PROVIDER_ALLOWLIST")
    allowed = {item.strip() for item in allowlist.split(",") if item.strip()}
    if not provider or not allowed or provider not in allowed:
        return None
    try:
        retry_count = int(
            _env("OC_GOVERNOR_RETRY_COUNT")
            or (
                "1"
                if "oc-repair" in {label.lower() for label in _labels(issue)}
                else "0"
            )
        )
        max_retries = int(_env("OC_GOVERNOR_MAX_RETRIES") or "1")
    except ValueError:
        return None
    if retry_count < 0 or max_retries < 0 or retry_count > max_retries:
        return None
    return provider, allowlist, retry_count, max_retries


def observe_issue(issue: dict[str, Any], *, now: datetime | None = None) -> str | None:
    """Return an issue-specific condition fingerprint, or None fail-closed."""
    if not _has_current_budget_marker(issue):
        return None
    policy = _authorized_budget_observation(issue)
    if policy is None:
        return None
    provider, allowlist, _, _ = policy

    try:
        estimated_costs = {
            tier: _env(f"OC_CLAUDE_{tier.upper()}_ESTIMATED_COST_USD")
            or DEFAULT_ESTIMATED_COST_USD[tier]
            for tier in TIERS
        }
        route = choose_route(
            title=str(issue.get("title") or ""),
            body=str(issue.get("body") or ""),
            labels=_labels(issue),
            default_tier=_env("OC_CLAUDE_DEFAULT_TIER") or "cheap",
            maximum_tier=_env("OC_CLAUDE_MAXIMUM_TIER") or "deep",
            estimated_cost_usd=estimated_costs,
        )
        estimated = Decimal(route.estimated_cost_usd)
        per_run_budget = _money("OC_GOVERNOR_PER_RUN_BUDGET_USD")
        daily_budget = _money("OC_GOVERNOR_DAILY_BUDGET_USD")
        monthly_budget = _money("OC_GOVERNOR_MONTHLY_BUDGET_USD")
        daily_spend = _money("OC_GOVERNOR_DAILY_SPEND_USD")
        monthly_spend = _money("OC_GOVERNOR_MONTHLY_SPEND_USD")
    except (InvalidOperation, ProviderNotRequired, TypeError, ValueError, KeyError):
        return None

    if per_run_budget <= 0 or daily_budget <= 0 or monthly_budget <= 0:
        return None
    if estimated > per_run_budget:
        reason = "BLOCKED_PER_RUN_BUDGET_EXCEEDED"
    elif daily_spend + estimated > daily_budget:
        reason = "BLOCKED_DAILY_BUDGET_EXCEEDED"
    elif monthly_spend + estimated > monthly_budget:
        reason = "BLOCKED_MONTHLY_BUDGET_EXCEEDED"
    else:
        # A clear condition is intentionally a different fingerprint from every
        # exhausted-budget reason, so a parked issue can be released only after
        # the relevant governed condition actually clears.
        reason = "BUDGET_CONDITION_CLEAR"

    return budget_blocker_fingerprint(
        reason,
        provider=provider,
        allowlist=allowlist,
        estimated_cost=str(estimated),
        per_run_budget=str(per_run_budget),
        daily_budget=str(daily_budget),
        monthly_budget=str(monthly_budget),
        now=now,
    )


def observe_issues(
    issues: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, str]:
    observations: dict[str, str] = {}
    for issue in issues:
        try:
            number = int(issue.get("number") or 0)
            if number > 0:
                fingerprint = observe_issue(issue, now=now)
                if fingerprint:
                    observations[str(number)] = fingerprint
        except (TypeError, ValueError):
            continue
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        with open(args.issues_json, encoding="utf-8") as handle:
            issues = json.load(handle)
        observations = observe_issues(issues if isinstance(issues, list) else [])
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        observations = {}
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(observations, handle, sort_keys=True)
    print(json.dumps(observations, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
