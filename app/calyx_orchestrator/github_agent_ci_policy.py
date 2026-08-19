from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

# GitHub check-run conclusions that mean the job actually ran and produced a
# real pass/fail verdict.
_SUCCESS_CONCLUSIONS = frozenset({"success"})
_FAILURE_CONCLUSIONS = frozenset({"failure"})

# Conclusions that mean the check never produced a real implementation
# verdict - the run itself was cancelled, timed out, blocked, or marked
# stale by GitHub, not that the code failed. These must never consume the
# coding-agent's bounded repair budget.
_INFRASTRUCTURE_CONCLUSIONS = frozenset(
    {"cancelled", "timed_out", "action_required", "stale"}
)


@dataclass(frozen=True, slots=True)
class CiCheckAssessment:
    required_checks_known: bool
    required_checks_pending: tuple[str, ...]
    required_checks_failed: tuple[str, ...]
    required_checks_succeeded: tuple[str, ...]
    infrastructure_failure: bool


@dataclass(frozen=True, slots=True)
class RequiredCiCheckPolicy:
    """Explicit, governed required-check roster.

    `orchid-calyx-backend` has neither branch-protection required-status-checks
    nor any repository ruleset configured (verified live, 2026-08-15) - GitHub
    itself cannot tell this system which checks are "required" for a PR.
    Completeness must therefore never be inferred from whatever subset of
    check-runs GitHub happens to return for a given head; it is only ever
    measured against this explicitly configured roster. A check name that
    never appears leaves `required_checks_known` False forever rather than
    being silently treated as passing or skipped - that is the intended,
    conservative fail-closed behavior, not an oversight.
    """

    required_checks: frozenset[str]

    def __post_init__(self) -> None:
        if not self.required_checks:
            raise ValueError("REQUIRED_CI_CHECK_POLICY_EMPTY_ROSTER")

    def digest(self) -> str:
        """Deterministic binding of the exact roster this assessment was made
        against - identical rosters produce identical digests and vice versa,
        so mission/dispatch evidence can record which policy version observed
        a given PR without needing a database column for the roster itself."""
        canonical = ",".join(sorted(self.required_checks))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def evaluate(self, check_run_conclusions: Mapping[str, str | None]) -> CiCheckAssessment:
        pending: list[str] = []
        failed: list[str] = []
        succeeded: list[str] = []
        infrastructure_failure = False
        for name in sorted(self.required_checks):
            conclusion = check_run_conclusions.get(name)
            if conclusion is None:
                pending.append(name)
            elif conclusion in _SUCCESS_CONCLUSIONS:
                succeeded.append(name)
            elif conclusion in _INFRASTRUCTURE_CONCLUSIONS:
                infrastructure_failure = True
            elif conclusion in _FAILURE_CONCLUSIONS:
                failed.append(name)
            else:
                # Unrecognized/non-terminal conclusion - fail closed as still
                # pending rather than guessing which bucket it belongs in.
                pending.append(name)
        return CiCheckAssessment(
            required_checks_known=not pending,
            required_checks_pending=tuple(pending),
            required_checks_failed=tuple(failed),
            required_checks_succeeded=tuple(succeeded),
            infrastructure_failure=infrastructure_failure,
        )
