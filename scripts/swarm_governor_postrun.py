#!/usr/bin/env python3
"""Swarm Governor post-run spend tracker.

Updates durable spend accumulators in GitHub Variables after a paid provider
run completes. Called at the end of each governed provider workflow; skipped
when the run was blocked (OC_GOVERNOR_RUN_AUTHORIZED != 'true').

GitHub Variables updated:
  OC_GOVERNOR_DAILY_SPEND_USD   — cumulative spend for today (UTC)
  OC_GOVERNOR_MONTHLY_SPEND_USD — cumulative spend for this month (UTC)
  OC_GOVERNOR_LAST_RUN_DATE     — YYYY-MM-DD of last successful update
  OC_GOVERNOR_LAST_RUN_MONTH    — YYYY-MM of last successful update

Date rollover: if LAST_RUN_DATE differs from today (UTC), daily spend resets to
zero before recording today's cost. Same logic for monthly.

Requires:
  GH_TOKEN with actions:write scope to update repository variables.
  GITHUB_REPOSITORY             — injected automatically in GitHub Actions.

Exits 0 always — spend-tracking failure must not block jobs that already
completed successfully, and must not surface as a false provider failure.

OC_GOVERNOR_ACTUAL_COST_USD is the authoritative cost for this run. Workflows
that cannot determine the actual cost should set it to "0" (no-op) or leave it
unset (skip tracking).
"""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v if v else None


def _decimal(raw: str | None, default: str = "0") -> Decimal:
    try:
        return Decimal(raw or default)
    except InvalidOperation:
        return Decimal(default)


def _gh_var_set(name: str, value: str, repo: str) -> bool:
    try:
        result = subprocess.run(
            ["gh", "variable", "set", name, "--body", value, "--repo", repo],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(
                f"[OC-GOVERNOR-POSTRUN] WARNING: gh variable set {name} failed "
                f"(rc={result.returncode}). Durable spend NOT updated. "
                "Ensure actions:write permission is set in the workflow.",
                flush=True,
            )
            return False
        return True
    except Exception as exc:
        print(
            f"[OC-GOVERNOR-POSTRUN] WARNING: gh variable set {name} raised: {exc}",
            flush=True,
        )
        return False


def main() -> None:
    repo = _env("GITHUB_REPOSITORY")
    if not repo:
        print("[OC-GOVERNOR-POSTRUN] GITHUB_REPOSITORY not set; skipping.", flush=True)
        return

    authorized = _env("OC_GOVERNOR_RUN_AUTHORIZED")
    if authorized != "true":
        print(
            "[OC-GOVERNOR-POSTRUN] Run was not authorized; no spend to record.",
            flush=True,
        )
        return

    actual_cost_raw = _env("OC_GOVERNOR_ACTUAL_COST_USD")
    if not actual_cost_raw:
        print(
            "[OC-GOVERNOR-POSTRUN] OC_GOVERNOR_ACTUAL_COST_USD not set; skipping.",
            flush=True,
        )
        return

    actual_cost = _decimal(actual_cost_raw)
    if actual_cost <= 0:
        print(f"[OC-GOVERNOR-POSTRUN] Cost {actual_cost!s} <= 0; skipping.", flush=True)
        return

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    last_date = _env("OC_GOVERNOR_LAST_RUN_DATE") or ""
    last_month = _env("OC_GOVERNOR_LAST_RUN_MONTH") or ""

    if last_date != today_str:
        daily_spend = Decimal(0)
        print(
            f"[OC-GOVERNOR-POSTRUN] Date rollover ({last_date!r} → {today_str}); daily reset.",
            flush=True,
        )
    else:
        daily_spend = _decimal(_env("OC_GOVERNOR_DAILY_SPEND_USD"))

    if last_month != month_str:
        monthly_spend = Decimal(0)
        print(
            f"[OC-GOVERNOR-POSTRUN] Month rollover ({last_month!r} → {month_str}); monthly reset.",
            flush=True,
        )
    else:
        monthly_spend = _decimal(_env("OC_GOVERNOR_MONTHLY_SPEND_USD"))

    new_daily = daily_spend + actual_cost
    new_monthly = monthly_spend + actual_cost

    print(
        f"[OC-GOVERNOR-POSTRUN] cost={actual_cost!s} "
        f"daily={daily_spend!s}→{new_daily!s} "
        f"monthly={monthly_spend!s}→{new_monthly!s}",
        flush=True,
    )

    _gh_var_set("OC_GOVERNOR_DAILY_SPEND_USD", str(new_daily), repo)
    _gh_var_set("OC_GOVERNOR_MONTHLY_SPEND_USD", str(new_monthly), repo)
    _gh_var_set("OC_GOVERNOR_LAST_RUN_DATE", today_str, repo)
    _gh_var_set("OC_GOVERNOR_LAST_RUN_MONTH", month_str, repo)


if __name__ == "__main__":
    main()
    sys.exit(0)
