#!/usr/bin/env python3
"""Swarm Governor precheck — workflow-layer policy gate for paid provider paths.

Reads policy state from environment variables (sourced from GitHub Variables),
evaluates the governor policy, and writes authorized/reason to $GITHUB_OUTPUT.
Always exits 0 so subsequent steps can branch on the output; the caller is
responsible for skipping provider steps when authorized=false.

Cross-runner enforcement layers:
  1. GitHub Actions concurrency group  — serialises to PAID_WORKER_CONCURRENCY=1
  2. GitHub Variables                   — carry durable budget spend across runs

Security invariants:
  - NO_API_MODE is evaluated first, fail-closed (absent → blocked).
  - Emergency kill switch blocks before any budget computation.
  - No credential value is read, logged, or passed through this script.

Environment variables consumed:
  NO_API_MODE                           — from vars.NO_API_MODE (primary kill switch)
  OC_GOVERNOR_EMERGENCY_KILL_SWITCH     — from vars.OC_GOVERNOR_EMERGENCY_KILL_SWITCH
  OC_GOVERNOR_PAID_EXECUTION_ENABLED    — from vars.OC_GOVERNOR_PAID_EXECUTION_ENABLED
  OC_GOVERNOR_PROVIDER                  — provider being requested (e.g. "anthropic")
  OC_GOVERNOR_PROVIDER_ALLOWLIST        — comma-separated list of allowed providers
  OC_GOVERNOR_RETRY_COUNT               — current retry attempt number
  OC_GOVERNOR_MAX_RETRIES               — maximum retries permitted
  OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD — estimated cost for this run
  OC_GOVERNOR_PER_RUN_BUDGET_USD        — per-run budget limit
  OC_GOVERNOR_DAILY_BUDGET_USD          — daily budget limit
  OC_GOVERNOR_MONTHLY_BUDGET_USD        — monthly budget limit
  OC_GOVERNOR_DAILY_SPEND_USD           — cumulative spend today (from GitHub Variable)
  OC_GOVERNOR_MONTHLY_SPEND_USD         — cumulative spend this month (from GitHub Variable)
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import oc_no_api_guard


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v if v else None


def _bool_env(name: str) -> bool:
    return (_env(name) or "").lower() in ("true", "1", "yes", "on")


def _decimal(raw: str | None, default: str = "0") -> Decimal:
    try:
        return Decimal(raw or default)
    except InvalidOperation:
        return Decimal(default)


def _write_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{key}={value}\n")


def main() -> None:
    no_api_raw = _env("NO_API_MODE")
    emergency_kill = _bool_env("OC_GOVERNOR_EMERGENCY_KILL_SWITCH")
    paid_execution_enabled = _bool_env("OC_GOVERNOR_PAID_EXECUTION_ENABLED")

    def block(reason: str, *, is_warning: bool = False) -> None:
        _write_output("authorized", "false")
        _write_output("reason", reason)
        lvl = "warning" if is_warning else "error"
        print(f"::{lvl}::[OC-GOVERNOR-PRECHECK] BLOCKED: {reason}", flush=True)

    def authorize(reason: str = "AUTHORIZED") -> None:
        _write_output("authorized", "true")
        _write_output("reason", reason)
        print(f"[OC-GOVERNOR-PRECHECK] {reason}", flush=True)

    # 1. NO_API_MODE — fail-closed; absent → blocked
    if oc_no_api_guard.evaluate(no_api_raw):
        block("BLOCKED_NO_API_MODE", is_warning=True)
        return

    # 2. Emergency kill switch
    if emergency_kill:
        block("BLOCKED_KILL_SWITCH")
        return

    # Probe/canary mode: only NO_API_MODE + kill switch apply; no paid budget checks.
    # Set OC_GOVERNOR_PAID_EXECUTION_ENABLED=true to enable full policy enforcement.
    if not paid_execution_enabled:
        authorize("AUTHORIZED_PROBE_MODE")
        return

    # 3. Full policy checks for paid execution lanes
    provider = _env("OC_GOVERNOR_PROVIDER") or ""
    allowlist_raw = _env("OC_GOVERNOR_PROVIDER_ALLOWLIST") or ""
    allowlist = frozenset(p.strip() for p in allowlist_raw.split(",") if p.strip())
    retry_count = int(_env("OC_GOVERNOR_RETRY_COUNT") or "0")
    max_retries = int(_env("OC_GOVERNOR_MAX_RETRIES") or "1")

    per_run_estimated = _decimal(_env("OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD"))
    per_run_budget = _decimal(_env("OC_GOVERNOR_PER_RUN_BUDGET_USD"))
    daily_budget = _decimal(_env("OC_GOVERNOR_DAILY_BUDGET_USD"))
    monthly_budget = _decimal(_env("OC_GOVERNOR_MONTHLY_BUDGET_USD"))
    daily_spend = _decimal(_env("OC_GOVERNOR_DAILY_SPEND_USD"))
    monthly_spend = _decimal(_env("OC_GOVERNOR_MONTHLY_SPEND_USD"))

    if not allowlist:
        block("BLOCKED_NO_PROVIDER_ALLOWLIST")
        return

    if provider and provider not in allowlist:
        block("BLOCKED_PROVIDER_NOT_ALLOWED")
        return

    if retry_count > max_retries:
        block("BLOCKED_RETRY_LIMIT_EXCEEDED")
        return

    if per_run_budget > 0 and per_run_estimated > per_run_budget:
        block("BLOCKED_PER_RUN_BUDGET_EXCEEDED")
        return

    if daily_budget > 0 and (daily_spend + per_run_estimated) > daily_budget:
        block("BLOCKED_DAILY_BUDGET_EXCEEDED")
        return

    if monthly_budget > 0 and (monthly_spend + per_run_estimated) > monthly_budget:
        block("BLOCKED_MONTHLY_BUDGET_EXCEEDED")
        return

    authorize()


if __name__ == "__main__":
    main()
