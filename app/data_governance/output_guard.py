from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import DataPolicyDecision, DisclosureMode


class ProtectedValueKind(StrEnum):
    RECORD = "RECORD"
    LOCALITY = "LOCALITY"
    IMAGE = "IMAGE"


@dataclass(frozen=True)
class ProtectedValue:
    label: str
    value: str
    kind: ProtectedValueKind = ProtectedValueKind.RECORD


@dataclass(frozen=True)
class GuardedText:
    text: str
    redacted_labels: tuple[str, ...]


def guard_generated_text(
    text: str,
    decision: DataPolicyDecision,
    protected_values: tuple[ProtectedValue, ...],
) -> GuardedText:
    """Redact exact protected values that exceed the authorized disclosure.

    This is a deterministic last-mile guard, not a substitute for semantic
    inference testing.  It is intended to stop direct re-emission of protected
    coordinates, site names, landowner names, restricted URLs, or other values
    supplied by the governed evidence layer.
    """

    guarded = text
    redacted: list[str] = []

    for protected in protected_values:
        value = protected.value.strip()
        if not value or _kind_is_disclosable(protected.kind, decision):
            continue
        if value in guarded:
            guarded = guarded.replace(value, f"[REDACTED:{protected.label}]")
            redacted.append(protected.label)

    return GuardedText(text=guarded, redacted_labels=tuple(sorted(set(redacted))))


def _kind_is_disclosable(
    kind: ProtectedValueKind,
    decision: DataPolicyDecision,
) -> bool:
    if not decision.allowed:
        return False
    if kind == ProtectedValueKind.LOCALITY:
        return decision.location_disclosure == DisclosureMode.FULL
    if kind == ProtectedValueKind.IMAGE:
        return decision.image_disclosure == DisclosureMode.FULL
    return decision.disclosure == DisclosureMode.FULL
