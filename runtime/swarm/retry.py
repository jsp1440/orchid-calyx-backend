"""Provider-economy retry classification.

The classifier deliberately prefers stopping over replaying an expensive model
session. Only transient infrastructure failures are retryable without escalation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryDecision:
    action: str
    reason: str
    consumes_model_retry: bool


def classify_retry(
    *,
    failure_class: str,
    retry_count: int,
    max_retries: int = 1,
) -> RetryDecision:
    kind = (failure_class or "unknown").strip().lower()

    if retry_count >= max_retries:
        return RetryDecision("stop", "retry-budget-exhausted", False)

    if kind in {"security", "billing", "budget", "provider-error", "unknown"}:
        return RetryDecision("stop", f"fail-closed:{kind}", False)

    if kind in {"ci-infrastructure", "runner-unavailable", "network-transient"}:
        return RetryDecision("retry-workflow", kind, False)

    if kind in {"deterministic-test", "lint", "compile", "yaml"}:
        return RetryDecision("repair-deterministically", kind, False)

    if kind in {"reasoning", "implementation", "max-turns"}:
        return RetryDecision("model-repair-once", kind, True)

    return RetryDecision("stop", f"unclassified:{kind}", False)
