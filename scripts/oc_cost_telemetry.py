"""OC-COST-001: cost observability for Orchid Continuum completion lanes.

Extracts provider-reported token and cost metadata from the Claude Code action
execution log and emits a telemetry summary that is safe to include in GitHub
issue comments.

Invariants:
- Unavailable metrics are UNKNOWN, never fabricated as 0.
- No prompt content, secret, protected locality data, or reasoning transcript
  appears in any telemetry field.
- Cache usage is recorded when the provider exposes it; absence is UNKNOWN.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


_UNKNOWN = "UNKNOWN"

# Fields that are safe to surface in a GitHub issue comment.
_SAFE_TELEMETRY_KEYS = frozenset({
    "provider",
    "model",
    "tier",
    "turns_used",
    "max_turns",
    "input_tokens",
    "output_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
    "normalized_cost_usd",
    "fallback_count",
    "outcome",
    "issue_number",
    "run_id",
    "reason",
})

# Patterns that would indicate unsafe content being leaked.
_SECRET_PATTERNS = re.compile(
    r"(sk-[A-Za-z0-9]{30,}|api[_-]?key[_-]?[:=]\s*\S+|password\s*[:=]\s*\S+|token\s*[:=]\s*[A-Za-z0-9+/]{20,})",
    re.IGNORECASE,
)


def _safe_int(value: Any) -> int | str:
    """Return int or UNKNOWN; never return 0 for a missing field."""
    if value is None:
        return _UNKNOWN
    try:
        return int(value)
    except (TypeError, ValueError):
        return _UNKNOWN


def extract_usage_from_execution_log(log_path: str) -> dict[str, Any]:
    """Parse the Claude Code action JSON log for token usage.

    Returns a dict with token fields set to int or UNKNOWN. Never fabricates zero
    for a field the provider did not report.

    Args:
        log_path: Absolute path to the execution log JSON file.
    """
    result: dict[str, Any] = {
        "input_tokens": _UNKNOWN,
        "output_tokens": _UNKNOWN,
        "cache_creation_tokens": _UNKNOWN,
        "cache_read_tokens": _UNKNOWN,
        "normalized_cost_usd": _UNKNOWN,
        "turns_used": _UNKNOWN,
    }
    if not log_path or not os.path.isfile(log_path):
        return result

    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return result

    turns = 0
    in_tok = 0
    out_tok = 0
    cache_create = 0
    cache_read = 0
    found_usage = False

    def _walk(node: Any) -> None:
        nonlocal turns, in_tok, out_tok, cache_create, cache_read, found_usage
        if isinstance(node, dict):
            if node.get("type") == "assistant":
                turns += 1
                usage = node.get("usage")
                if isinstance(usage, dict) and "input_tokens" in usage:
                    found_usage = True
                    in_tok += int(usage.get("input_tokens") or 0)
                    out_tok += int(usage.get("output_tokens") or 0)
                    cache_create += int(usage.get("cache_creation_input_tokens") or 0)
                    cache_read += int(usage.get("cache_read_input_tokens") or 0)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(raw)

    result["turns_used"] = turns if turns > 0 else _UNKNOWN
    if found_usage:
        result["input_tokens"] = in_tok
        result["output_tokens"] = out_tok
        result["cache_creation_tokens"] = cache_create if cache_create > 0 else _UNKNOWN
        result["cache_read_tokens"] = cache_read if cache_read > 0 else _UNKNOWN
    return result


def safe_telemetry_summary(
    *,
    provider: str,
    tier: str,
    model: str,
    max_turns: int | str,
    reason: str,
    outcome: str,
    usage: dict[str, Any] | None = None,
    fallback_count: int = 0,
    issue_number: int | str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a telemetry dict safe to include in a GitHub issue comment.

    Args:
        provider: Provider name (e.g. "claude", "gemini", "openai").
        tier: Router tier ("cheap", "standard", "deep").
        model: Model name as reported by the router.
        max_turns: Turn ceiling this run was granted.
        reason: Router reason string.
        outcome: One of "delivered", "repair", "blocked", "runtime_backoff".
        usage: Output of extract_usage_from_execution_log.
        fallback_count: Number of provider fallbacks taken (0 = no fallback).
        issue_number: The GitHub issue number (for attribution, not content).
        run_id: The GitHub Actions run ID (public URL component only).

    Returns:
        Dict with only safe fields; secrets and prompt content are excluded.
    """
    u = usage or {}
    summary: dict[str, Any] = {
        "provider": str(provider),
        "tier": str(tier),
        "model": str(model),
        "max_turns": max_turns,
        "reason": str(reason),
        "turns_used": u.get("turns_used", _UNKNOWN),
        "input_tokens": u.get("input_tokens", _UNKNOWN),
        "output_tokens": u.get("output_tokens", _UNKNOWN),
        "cache_creation_tokens": u.get("cache_creation_tokens", _UNKNOWN),
        "cache_read_tokens": u.get("cache_read_tokens", _UNKNOWN),
        "normalized_cost_usd": u.get("normalized_cost_usd", _UNKNOWN),
        "fallback_count": fallback_count,
        "outcome": str(outcome),
    }
    if issue_number is not None:
        summary["issue_number"] = str(issue_number)
    if run_id is not None:
        summary["run_id"] = str(run_id)

    assert set(summary.keys()) <= _SAFE_TELEMETRY_KEYS, (
        f"Telemetry contains unexpected key(s): {set(summary) - _SAFE_TELEMETRY_KEYS}"
    )
    serialized = json.dumps(summary)
    assert not _SECRET_PATTERNS.search(serialized), (
        "Telemetry summary matched a secret pattern — aborting to prevent data leakage"
    )
    return summary


def format_telemetry_comment(summary: dict[str, Any]) -> str:
    """Format a safe telemetry summary as a GitHub issue comment line."""
    parts = [
        f"provider={summary.get('provider', _UNKNOWN)}",
        f"tier={summary.get('tier', _UNKNOWN)}",
        f"model={summary.get('model', _UNKNOWN)}",
        f"turns={summary.get('turns_used', _UNKNOWN)}/{summary.get('max_turns', _UNKNOWN)}",
        f"in={summary.get('input_tokens', _UNKNOWN)}",
        f"out={summary.get('output_tokens', _UNKNOWN)}",
        f"cache_r={summary.get('cache_read_tokens', _UNKNOWN)}",
        f"outcome={summary.get('outcome', _UNKNOWN)}",
    ]
    return "[OC-TELEMETRY] " + " ".join(parts)
