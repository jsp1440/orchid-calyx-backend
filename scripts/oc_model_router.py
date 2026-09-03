#!/usr/bin/env python3
"""Cost-aware Claude routing for Orchid Continuum autonomous completion lanes.

The router is deliberately deterministic and repository-local. It does not call a
model to decide which model to call. Cheap is the default; complexity signals and
bounded repair retries may promote a task one tier at a time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Iterable


TIERS = ("cheap", "standard", "deep")
DEFAULT_MODELS = {
    "cheap": "claude-haiku-4-5",
    "standard": "claude-sonnet-5",
    "deep": "claude-opus-5",
}
DEFAULT_MAX_TURNS = {"cheap": 24, "standard": 45, "deep": 70}

DEEP_SIGNALS = (
    "architecture",
    "architectural",
    "race condition",
    "deadlock",
    "concurrency",
    "atomic",
    "cross-repo",
    "cross repository",
    "migration",
    "security boundary",
    "scientific inference",
    "provenance conflict",
    "nondeterministic",
    "flaky",
)
STANDARD_SIGNALS = (
    "implement",
    "integration",
    "refactor",
    "multi-file",
    "multiple files",
    "debug",
    "failing test",
    "repair",
    "workflow",
    "provider fallback",
)


@dataclass(frozen=True)
class Route:
    tier: str
    model: str
    max_turns: int
    reason: str
    escalated: bool


def _labels(raw: str | Iterable[str]) -> set[str]:
    if isinstance(raw, str):
        parts = re.split(r"[\s,]+", raw.strip()) if raw.strip() else []
    else:
        parts = list(raw)
    return {str(item).strip().lower() for item in parts if str(item).strip()}


def _rank(tier: str) -> int:
    try:
        return TIERS.index(tier)
    except ValueError as exc:
        raise ValueError(f"unknown model tier: {tier}") from exc


def _clamp(tier: str, maximum: str) -> str:
    return TIERS[min(_rank(tier), _rank(maximum))]


def _promote(tier: str, maximum: str) -> str:
    return TIERS[min(_rank(tier) + 1, _rank(maximum))]


def choose_route(
    *,
    title: str,
    body: str,
    labels: str | Iterable[str] = (),
    default_tier: str = "cheap",
    maximum_tier: str = "deep",
    models: dict[str, str] | None = None,
    max_turns: dict[str, int] | None = None,
) -> Route:
    """Choose the least-expensive tier justified by task evidence.

    Explicit ``oc-model-*`` labels are authoritative. Otherwise the task starts at
    the configured default tier, is promoted for complexity signals, and receives
    one additional bounded promotion when ``oc-repair`` is present. The latter
    makes existing repair/retry flow the escalation mechanism instead of repeatedly
    spending at the same insufficient tier.
    """

    if default_tier not in TIERS or maximum_tier not in TIERS:
        raise ValueError("default_tier and maximum_tier must be cheap, standard, or deep")
    if _rank(default_tier) > _rank(maximum_tier):
        raise ValueError("default_tier cannot exceed maximum_tier")

    labels_set = _labels(labels)
    combined = f"{title}\n{body}".lower()
    tier = default_tier
    reasons: list[str] = [f"default={default_tier}"]

    explicit = [name for name in TIERS if f"oc-model-{name}" in labels_set]
    if explicit:
        tier = max(explicit, key=_rank)
        reasons = [f"explicit-label=oc-model-{tier}"]
    else:
        if any(signal in combined for signal in DEEP_SIGNALS):
            tier = "deep"
            reasons.append("deep-complexity-signal")
        elif any(signal in combined for signal in STANDARD_SIGNALS):
            tier = max((tier, "standard"), key=_rank)
            reasons.append("standard-complexity-signal")

    tier = _clamp(tier, maximum_tier)
    before_repair = tier
    if "oc-repair" in labels_set:
        tier = _promote(tier, maximum_tier)
        if tier != before_repair:
            reasons.append(f"repair-escalation={before_repair}->{tier}")
        else:
            reasons.append("repair-escalation=capped")

    configured_models = {**DEFAULT_MODELS, **(models or {})}
    configured_turns = {**DEFAULT_MAX_TURNS, **(max_turns or {})}
    return Route(
        tier=tier,
        model=configured_models[tier],
        max_turns=int(configured_turns[tier]),
        reason=";".join(reasons),
        escalated=(tier != default_tier),
    )


def _env_model(tier: str) -> str:
    return os.getenv(f"OC_CLAUDE_{tier.upper()}_MODEL", DEFAULT_MODELS[tier])


def _env_turns(tier: str) -> int:
    raw = os.getenv(f"OC_CLAUDE_{tier.upper()}_MAX_TURNS")
    return int(raw) if raw else DEFAULT_MAX_TURNS[tier]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--labels", default="")
    parser.add_argument("--default-tier", default=os.getenv("OC_CLAUDE_DEFAULT_TIER", "cheap"))
    parser.add_argument("--maximum-tier", default=os.getenv("OC_CLAUDE_MAXIMUM_TIER", "deep"))
    parser.add_argument("--github-output", default="")
    args = parser.parse_args()

    route = choose_route(
        title=args.title,
        body=args.body,
        labels=args.labels,
        default_tier=args.default_tier,
        maximum_tier=args.maximum_tier,
        models={tier: _env_model(tier) for tier in TIERS},
        max_turns={tier: _env_turns(tier) for tier in TIERS},
    )
    payload = asdict(route)
    print(json.dumps(payload, sort_keys=True))

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            for key, value in payload.items():
                rendered = str(value).lower() if isinstance(value, bool) else str(value)
                handle.write(f"{key}={rendered}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
