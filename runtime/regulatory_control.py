"""Deterministic regulatory checkpoint for the OC autonomous runtime.

This module is intentionally small and provider-free. It translates observable
runtime state into one of three control decisions without performing writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from runtime.mission_genome import mission_context

RegulatoryAction = Literal["activate", "repress", "escalate"]


@dataclass(frozen=True)
class RegulatoryDecision:
    action: RegulatoryAction
    reasons: tuple[str, ...] = ()
    policy: str = "oc-genome-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reasons": list(self.reasons),
            "policy": self.policy,
            "mission": mission_context(),
        }


def default_regulatory_decision(heartbeat_result: Any) -> dict[str, Any]:
    """Backward-compatible default: allow the existing runtime cycle to proceed."""
    return RegulatoryDecision(
        action="activate",
        reasons=(
            "no explicit regulator configured; preserve existing execution behavior",
            "autonomous work remains subordinate to the Orchid Continuum mission",
        ),
    ).to_dict()


def normalize_regulatory_decision(value: Any) -> RegulatoryDecision:
    """Normalize a callback result and fail closed on invalid decisions."""
    if isinstance(value, RegulatoryDecision):
        return value

    if not isinstance(value, dict):
        return RegulatoryDecision(
            action="escalate",
            reasons=("regulator returned a non-dictionary decision",),
        )

    action = str(value.get("action") or "").strip().lower()
    if action not in {"activate", "repress", "escalate"}:
        return RegulatoryDecision(
            action="escalate",
            reasons=(f"invalid regulatory action: {action or 'missing'}",),
        )

    raw_reasons = value.get("reasons") or ()
    if isinstance(raw_reasons, str):
        reasons = (raw_reasons,)
    else:
        reasons = tuple(str(item) for item in raw_reasons)

    return RegulatoryDecision(
        action=action,  # type: ignore[arg-type]
        reasons=reasons,
        policy=str(value.get("policy") or "oc-genome-v1"),
    )
