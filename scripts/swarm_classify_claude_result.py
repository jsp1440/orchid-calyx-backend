#!/usr/bin/env python3
"""Classify the Claude direct-executor terminal state from the execution JSON.

This is the authoritative classifier used by the completion-lane workflow.
Extracting it from YAML/bash to Python makes it unit-testable without live
provider calls or GitHub Actions.

Classification precedence (most-specific first):
  1. no_execution      — execution file absent; no model ran
  2. billing_exhausted — credit/billing exhaustion signals
  3. security          — 401/403 or API-key signals
  4. max_turns         — bounded turn ceiling reached
  5. no_durable_change — model completed without repository changes (not a provider fault)
  6. safe_provider     — transient 5xx provider error (retryable via concurrency slot)
  7. provider_failure  — failure with model usage evidence but no specific classification
  8. no_model_usage    — step ran but no model turns were observed
  9. workflow signals  — validation_skip or further safe_provider indicators
 10. unknown           — unclassified failure
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def classify(
    *,
    execution_file: str | None,
    outcome: str,
    conclusion: str,
) -> tuple[str, bool]:
    """Return (kind, fallback_allowed) for a completed Claude executor step.

    Parameters
    ----------
    execution_file:
        Path to the execution JSON written by swarm_anthropic_direct.py, or
        empty/None when the executor step was skipped or produced no file.
    outcome:
        The step outcome reported by GitHub Actions: "success", "failure",
        "cancelled", or "skipped".
    conclusion:
        The ``conclusion`` output written by the executor to GITHUB_OUTPUT:
        "success" or "failure".
    """
    # ── 1. no_execution ──────────────────────────────────────────────────────
    if not execution_file or not Path(execution_file).is_file():
        return "no_execution", False

    try:
        raw = json.loads(Path(execution_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "no_execution", False

    result_obj: dict[str, Any] = {}
    if isinstance(raw, dict) and raw.get("type") == "result":
        result_obj = raw

    result_error = _str(result_obj.get("error"))
    api_error_status = _str(result_obj.get("api_error_status"))
    subtype = _str(result_obj.get("subtype"))
    is_error = str(result_obj.get("is_error", "")).lower() == "true"
    result_text = _str(result_obj.get("result"))
    num_turns_raw = result_obj.get("num_turns")
    model_usage = result_obj.get("modelUsage") or {}
    model_usage_count = len(model_usage) if isinstance(model_usage, dict) else 0

    num_turns: int | None = None
    if isinstance(num_turns_raw, int):
        num_turns = num_turns_raw
    elif isinstance(num_turns_raw, str) and num_turns_raw.isdigit():
        num_turns = int(num_turns_raw)

    combined = f"{result_text} {result_error} {api_error_status} {subtype} {conclusion}".lower()

    # ── 2. billing_exhausted ─────────────────────────────────────────────────
    if result_error == "billing_error" or any(
        phrase in combined
        for phrase in (
            "credit balance",
            "insufficient credit",
            "reached your specified api usage limits",
            "api usage limit",
        )
    ):
        return "billing_exhausted", False

    # ── 3. security ──────────────────────────────────────────────────────────
    if api_error_status in {"401", "403"} or any(
        phrase in combined for phrase in ("invalid api key", "invalid_api_key")
    ):
        return "security", False

    # ── 4. max_turns ─────────────────────────────────────────────────────────
    if result_error == "max_turns" or any(
        phrase in combined
        for phrase in ("error_max_turns", "max_turns", "max turns", "maximum turns")
    ):
        return "max_turns", False

    # ── 5. no_durable_change ─────────────────────────────────────────────────
    # Model executed successfully but decided no repository changes were needed.
    # This is NOT a provider fault — the execution slot worked fine. Route to
    # oc-repair for a human-assisted or bounded retry, same as max_turns.
    if result_error == "no_durable_change":
        return "no_durable_change", False

    # ── 6. safe_provider (5xx HTTP) ──────────────────────────────────────────
    if api_error_status and api_error_status.isdigit() and api_error_status[0] == "5":
        return "safe_provider", True

    # ── 7. provider_failure ──────────────────────────────────────────────────
    # Generic failure with confirmed model usage: something ran but ended badly
    # in a way we haven't classified more precisely above.
    if conclusion == "failure" and model_usage_count != 0:
        return "provider_failure", False

    # ── 8. no_model_usage ────────────────────────────────────────────────────
    if num_turns is None or num_turns < 1 or model_usage_count == 0:
        return "no_model_usage", False

    # ── 9. outcome-based refinement (step failed but execution file present) ─
    if outcome != "success":
        if any(
            phrase in combined
            for phrase in ("workflow validation failed", "action skipped")
        ):
            return "workflow_validation_skip", False
        if any(
            phrase in combined
            for phrase in (
                "rate_limit",
                "rate limit",
                "overloaded",
                "service unavailable",
                "connection_error",
                "timeout",
            )
        ):
            return "safe_provider", True
        if (
            is_error
            and subtype == "success"
            and num_turns is not None
            and num_turns <= 1
            and model_usage_count == 0
        ):
            # Degraded-runtime signature: opaque provider failure with no real
            # model execution evidence.
            return "safe_provider", True
        return "unknown", False

    # ── 10. healthy ──────────────────────────────────────────────────────────
    return "healthy", False


def _github_output(path: str, values: dict[str, str]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in values.items())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify Claude executor terminal state"
    )
    parser.add_argument("--execution-file", default="")
    parser.add_argument("--outcome", default="")
    parser.add_argument("--conclusion", default="")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    args = parser.parse_args()

    kind, fallback_allowed = classify(
        execution_file=args.execution_file or None,
        outcome=args.outcome,
        conclusion=args.conclusion,
    )

    print(f"[OC-CLASSIFIER] kind={kind} fallback_allowed={fallback_allowed}")
    sys.stdout.flush()

    if args.github_output:
        _github_output(
            args.github_output,
            {
                "kind": kind,
                "fallback_allowed": str(fallback_allowed).lower(),
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
