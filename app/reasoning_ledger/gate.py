"""Publication gate for reasoning ledgers.

A ledger must pass all gate checks before it may be published.  The gate
evaluates three hard rules:

1. No unresolved conflict entries.
2. All conclusion entries have a confidence score >= MIN_CONFIDENCE.
3. At least one APPROVED review decision from a named human reviewer.

Failing any rule produces a structured :class:`GateViolation` list, and
raising a :exc:`LedgerPublicationError` prevents the publish operation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    LedgerEntryKind,
    LedgerPublicationError,
    ReasoningLedger,
)

_MIN_CONFIDENCE = 0.6  # must match ReasoningLedger.MIN_PUBLICATION_CONFIDENCE


@dataclass(frozen=True, slots=True)
class GateViolation:
    """A single reason why a ledger cannot be published."""

    code: str
    message: str


def evaluate(ledger: ReasoningLedger) -> list[GateViolation]:
    """Return a list of :class:`GateViolation` objects for the ledger.

    An empty list means the ledger passes all publication gate checks.
    """
    violations: list[GateViolation] = []

    # Use the model property so that conflicts marked as resolved/superseded
    # via resolved_conflict_ids are correctly excluded.
    unresolved = ledger.unresolved_conflicts
    if unresolved:
        violations.append(
            GateViolation(
                code="UNRESOLVED_CONFLICTS",
                message=(
                    f"{len(unresolved)} unresolved conflict "
                    f"{'entry' if len(unresolved) == 1 else 'entries'} "
                    "must be resolved or deferred before publication"
                ),
            )
        )

    conclusion_entries = [
        e for e in ledger.entries if e.kind is LedgerEntryKind.CONCLUSION
    ]
    if not conclusion_entries:
        violations.append(
            GateViolation(
                code="NO_CONCLUSION",
                message="at least one CONCLUSION entry is required for publication",
            )
        )
    else:
        low_confidence = [
            e
            for e in conclusion_entries
            if e.uncertainty is None or e.uncertainty.confidence < _MIN_CONFIDENCE
        ]
        if low_confidence:
            violations.append(
                GateViolation(
                    code="LOW_CONFIDENCE",
                    message=(
                        f"{len(low_confidence)} conclusion "
                        f"{'entry' if len(low_confidence) == 1 else 'entries'} "
                        f"below the minimum confidence threshold of {_MIN_CONFIDENCE}"
                    ),
                )
            )

    # Use the version-bound has_human_approval property so that approvals issued
    # for an earlier version do not satisfy the gate after a subsequent append.
    if not ledger.has_human_approval:
        violations.append(
            GateViolation(
                code="MISSING_HUMAN_APPROVAL",
                message=(
                    "explicit human approval (REVIEW_DECISION with outcome=approved) "
                    "bound to the current ledger version is required before publication"
                ),
            )
        )

    return violations


def assert_publishable(ledger: ReasoningLedger) -> None:
    """Raise :exc:`LedgerPublicationError` if the ledger fails any gate check."""
    violations = evaluate(ledger)
    if violations:
        details = "; ".join(v.message for v in violations)
        raise LedgerPublicationError(
            f"ledger '{ledger.ledger_id}' cannot be published: {details}"
        )
