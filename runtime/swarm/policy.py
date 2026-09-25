"""GovernorPolicy — the 12 policy controls for the Swarm Execution Governor."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .exceptions import GovernorPolicyError


@dataclass
class GovernorPolicy:
    """All twelve policy controls for one governed swarm execution lane.

    Fail-closed invariants:
    - auto_refill must remain False — budget refill is never automatic.
    - When paid_execution_enabled=True, all three budget fields and a non-empty
      provider_allowlist are required; missing any raises GovernorPolicyError.
    - paid_worker_concurrency must be >= 1.
    - max_retries must be >= 0.
    """

    # 1. PAID_WORKER_CONCURRENCY
    paid_worker_concurrency: int = 1
    # 2. MAX_RETRIES
    max_retries: int = 1
    # 3. STOP_ON_PROVIDER_ERROR
    stop_on_provider_error: bool = True
    # 4. STOP_ON_BUDGET_THRESHOLD
    stop_on_budget_threshold: bool = True
    # 5. AUTO_REFILL — must always be False
    auto_refill: bool = False
    # 6. PER_RUN_BUDGET
    per_run_budget: Decimal | None = None
    # 7. DAILY_BUDGET
    daily_budget: Decimal | None = None
    # 8. MONTHLY_BUDGET
    monthly_budget: Decimal | None = None
    # 9. EMERGENCY_KILL_SWITCH
    emergency_kill_switch: bool = False
    # 10. PROVIDER_ALLOWLIST
    provider_allowlist: frozenset[str] = field(default_factory=frozenset)
    # 11. PROVIDER_PRIORITY
    provider_priority: tuple[str, ...] = field(default_factory=tuple)
    # Gate: paid execution requires all budgets + allowlist
    paid_execution_enabled: bool = False

    def __post_init__(self) -> None:
        # Normalize budget types — accept int/float/str, convert to Decimal
        for attr in ("per_run_budget", "daily_budget", "monthly_budget"):
            val = getattr(self, attr)
            if val is not None and not isinstance(val, Decimal):
                try:
                    setattr(self, attr, Decimal(str(val)))
                except InvalidOperation as exc:
                    raise GovernorPolicyError(
                        f"INVALID_BUDGET_{attr.upper()}: {val!r}"
                    ) from exc

        if self.auto_refill:
            raise GovernorPolicyError("AUTO_REFILL_PROHIBITED")
        if self.paid_worker_concurrency < 1:
            raise GovernorPolicyError("PAID_WORKER_CONCURRENCY_MUST_BE_POSITIVE")
        if self.max_retries < 0:
            raise GovernorPolicyError("MAX_RETRIES_MUST_BE_NON_NEGATIVE")
        if self.paid_execution_enabled:
            if self.per_run_budget is None:
                raise GovernorPolicyError("PER_RUN_BUDGET_REQUIRED_WHEN_PAID_ENABLED")
            if self.daily_budget is None:
                raise GovernorPolicyError("DAILY_BUDGET_REQUIRED_WHEN_PAID_ENABLED")
            if self.monthly_budget is None:
                raise GovernorPolicyError("MONTHLY_BUDGET_REQUIRED_WHEN_PAID_ENABLED")
            if not self.provider_allowlist:
                raise GovernorPolicyError(
                    "PROVIDER_ALLOWLIST_REQUIRED_WHEN_PAID_ENABLED"
                )

    def ordered_providers(self) -> list[str]:
        """Return allowed providers sorted by priority order.

        Providers listed in provider_priority come first (in order), followed
        by any remaining allowlist members in sorted order.
        """
        seen: set[str] = set()
        result: list[str] = []
        for p in self.provider_priority:
            if p in self.provider_allowlist and p not in seen:
                result.append(p)
                seen.add(p)
        for p in sorted(self.provider_allowlist):
            if p not in seen:
                result.append(p)
        return result

    def snapshot(self) -> dict:
        """Return a safe, JSON-serialisable copy of this policy."""
        return {
            "paid_worker_concurrency": self.paid_worker_concurrency,
            "max_retries": self.max_retries,
            "stop_on_provider_error": self.stop_on_provider_error,
            "stop_on_budget_threshold": self.stop_on_budget_threshold,
            "auto_refill": self.auto_refill,
            "per_run_budget": str(self.per_run_budget)
            if self.per_run_budget is not None
            else None,
            "daily_budget": str(self.daily_budget)
            if self.daily_budget is not None
            else None,
            "monthly_budget": str(self.monthly_budget)
            if self.monthly_budget is not None
            else None,
            "emergency_kill_switch": self.emergency_kill_switch,
            "provider_allowlist": sorted(self.provider_allowlist),
            "provider_priority": list(self.provider_priority),
            "paid_execution_enabled": self.paid_execution_enabled,
        }
