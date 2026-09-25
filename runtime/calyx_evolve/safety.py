"""Hard safety constraints evaluated before any candidate may be ranked.

These are not weights in a score.  A candidate that trips a hard constraint is
ineligible regardless of how well it reconciles names, and a candidate that
*asks* to mutate production or activate taxonomy never runs at all.

Three distinct dispositions:

``reject_before_execution``
    The request itself is disqualifying.  The EXPERIMENT stage refuses to run
    the candidate and records a terminal ``rejected_unsafe`` run.
``ineligible``
    The candidate ran, but its behaviour disqualifies it from ranking.
``blocks_promotion``
    The candidate may be ranked and compared, but may never be promoted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from runtime.calyx_evolve.candidates import Candidate
from runtime.calyx_evolve.redaction import locality_violations

DISPOSITION_REJECT = "reject_before_execution"
DISPOSITION_INELIGIBLE = "ineligible"
DISPOSITION_BLOCKS_PROMOTION = "blocks_promotion"

CODE_PRODUCTION_MUTATION = "PRODUCTION_MUTATION_REQUESTED"
CODE_TAXONOMY_ACTIVATION = "TAXONOMY_ACTIVATION_REQUESTED"
CODE_PROTECTED_LOCALITY = "PROTECTED_LOCALITY_EXPOSED"
CODE_MISSING_PROVENANCE = "MISSING_REQUIRED_PROVENANCE"
CODE_SCOPE_NOT_STAGING = "EXECUTION_SCOPE_NOT_STAGING"

SCOPE_STAGING_ONLY = "STAGING_ONLY"


@dataclass(frozen=True, slots=True)
class SafetyViolation:
    code: str
    disposition: str
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "disposition": self.disposition,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


class UnsafeCandidate(RuntimeError):
    """Raised when a candidate must not be executed at all."""

    def __init__(self, violations: Iterable[SafetyViolation]) -> None:
        self.violations = tuple(violations)
        codes = ", ".join(violation.code for violation in self.violations)
        super().__init__(f"candidate rejected before execution: {codes}")


def screen_candidate(candidate: Candidate, *, execution_scope: str) -> tuple[SafetyViolation, ...]:
    """Return pre-execution violations for ``candidate``.

    Any returned violation carries disposition ``reject_before_execution``: the
    caller must not run the candidate.
    """

    violations: list[SafetyViolation] = []
    if execution_scope != SCOPE_STAGING_ONLY:
        violations.append(
            SafetyViolation(
                CODE_SCOPE_NOT_STAGING,
                DISPOSITION_REJECT,
                f"execution scope {execution_scope!r} is not {SCOPE_STAGING_ONLY}",
            )
        )
    if candidate.config.request_production_write:
        violations.append(
            SafetyViolation(
                CODE_PRODUCTION_MUTATION,
                DISPOSITION_REJECT,
                "candidate requested a production database or Knowledge Graph write",
                ("config.request_production_write",),
            )
        )
    if candidate.config.request_taxonomy_activation:
        violations.append(
            SafetyViolation(
                CODE_TAXONOMY_ACTIVATION,
                DISPOSITION_REJECT,
                "candidate requested taxonomy activation without human scientific review",
                ("config.request_taxonomy_activation",),
            )
        )
    return tuple(violations)


def assert_safe_to_execute(candidate: Candidate, *, execution_scope: str) -> None:
    """Raise :class:`UnsafeCandidate` when ``candidate`` may not run."""

    violations = screen_candidate(candidate, execution_scope=execution_scope)
    if violations:
        raise UnsafeCandidate(violations)


def screen_output(artifact: Mapping[str, Any]) -> tuple[SafetyViolation, ...]:
    """Return post-execution violations found in a candidate's emitted output."""

    paths = locality_violations(artifact)
    if not paths:
        return ()
    return (
        SafetyViolation(
            CODE_PROTECTED_LOCALITY,
            DISPOSITION_INELIGIBLE,
            "candidate output exposed protected locality",
            tuple(sorted(paths)),
        ),
    )


def provenance_violation(completeness: float | None) -> SafetyViolation | None:
    """Return a promotion-blocking violation when provenance is incomplete."""

    if completeness is None:
        return SafetyViolation(
            CODE_MISSING_PROVENANCE,
            DISPOSITION_BLOCKS_PROMOTION,
            "provenance completeness was not measured",
        )
    if completeness < 1.0:
        return SafetyViolation(
            CODE_MISSING_PROVENANCE,
            DISPOSITION_BLOCKS_PROMOTION,
            f"provenance completeness {completeness:.4f} is below the required 1.0",
        )
    return None


def is_eligible(violations: Iterable[SafetyViolation]) -> bool:
    """A candidate is eligible for ranking only with no reject/ineligible finding."""

    return not any(
        violation.disposition in (DISPOSITION_REJECT, DISPOSITION_INELIGIBLE)
        for violation in violations
    )


def is_promotable(violations: Iterable[SafetyViolation]) -> bool:
    """A candidate may be proposed for promotion only with no violations at all."""

    return not tuple(violations)
