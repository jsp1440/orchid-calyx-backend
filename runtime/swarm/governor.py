"""SwarmExecutionGovernor — fail-closed cost-control gate for paid provider execution."""

from __future__ import annotations

import sys
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .exceptions import GovernorBlockedError
from .ledger import ExecutionLedger
from .models import ExecutionRequest, GovernorDecision, LedgerEntry
from .policy import GovernorPolicy

# Ensure scripts/ is on the path so oc_no_api_guard is importable
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import oc_no_api_guard as _guard  # noqa: E402


class SwarmExecutionGovernor:
    """Fail-closed gate between the Swarm scheduler and all paid provider paths.

    Execution path:
      scheduler → authorize/begin → policy evaluation → AUTHORIZED or BLOCKED
      → (if authorized) provider worker → end → ledger update

    All policy checks are evaluated under a single lock to prevent TOCTOU
    races on budget and concurrency state.

    Security invariants:
    - NO credential values are stored, logged, or passed through this class.
    - NO_API_MODE guard is always consulted first; a missing guard module is
      treated as blocked (fail-closed).
    - auto_refill is unconditionally prohibited; the policy validator enforces this.
    - Providers not in the explicit allowlist are always blocked.
    - Missing budgets when paid_execution_enabled=True raise GovernorPolicyError
      at construction time, so the governor never reaches a runtime ambiguous state.
    """

    def __init__(
        self,
        policy: GovernorPolicy,
        *,
        no_api_mode_raw: str | None = None,
    ) -> None:
        self._policy = policy
        self._no_api_mode_raw = no_api_mode_raw
        self._ledger = ExecutionLedger()
        self._lock = threading.Lock()
        self._active_workers: int = 0
        self._provider_error_stop: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def policy(self) -> GovernorPolicy:
        return self._policy

    @property
    def ledger(self) -> ExecutionLedger:
        return self._ledger

    @property
    def active_workers(self) -> int:
        with self._lock:
            return self._active_workers

    # ------------------------------------------------------------------
    # Policy evaluation (stateless read)
    # ------------------------------------------------------------------

    def authorize(self, request: ExecutionRequest) -> GovernorDecision:
        """Evaluate policy without allocating a slot or creating a ledger entry."""
        with self._lock:
            return self._evaluate(request)

    # ------------------------------------------------------------------
    # Transactional slot management
    # ------------------------------------------------------------------

    def begin(self, request: ExecutionRequest) -> str:
        """Authorize + allocate concurrency slot + create ledger entry.

        Returns the entry_id for the new LedgerEntry.
        Raises GovernorBlockedError if any policy check fails.
        """
        with self._lock:
            decision = self._evaluate(request)
            if not decision.authorized:
                raise GovernorBlockedError(decision.reason)
            entry_id = str(uuid.uuid4())
            entry = LedgerEntry(
                entry_id=entry_id,
                issue_task_id=request.issue_task_id,
                provider=request.provider,
                worker_lane=request.worker_lane,
                started_at=datetime.now(timezone.utc),
                retry_count=request.retry_count,
                governing_policy_snapshot=self._policy.snapshot(),
                estimated_cost_usd=request.estimated_cost_usd,
            )
            self._ledger._add_locked(entry)
            self._active_workers += 1
        return entry_id

    def end(
        self,
        entry_id: str,
        *,
        succeeded: bool,
        termination_reason: str,
        estimated_tokens: int | None = None,
    ) -> LedgerEntry:
        """Release concurrency slot and finalize the ledger entry.

        If succeeded=False and stop_on_provider_error=True, subsequent begin()
        calls will be blocked until reset_provider_error_stop() is called.
        """
        with self._lock:
            updated = self._ledger._update_locked(
                entry_id,
                ended_at=datetime.now(timezone.utc),
                succeeded=succeeded,
                termination_reason=termination_reason,
                estimated_tokens=estimated_tokens,
            )
            self._active_workers = max(0, self._active_workers - 1)
            if not succeeded and self._policy.stop_on_provider_error:
                self._provider_error_stop = True
        return updated

    # ------------------------------------------------------------------
    # Control signals
    # ------------------------------------------------------------------

    def notify_provider_error(self) -> None:
        """Signal an out-of-band provider error; engages stop if policy requires it."""
        with self._lock:
            if self._policy.stop_on_provider_error:
                self._provider_error_stop = True

    def reset_provider_error_stop(self) -> None:
        """Clear the provider-error stop flag; owner-triggered recovery only."""
        with self._lock:
            self._provider_error_stop = False

    # ------------------------------------------------------------------
    # Internal evaluation (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _evaluate(self, request: ExecutionRequest) -> GovernorDecision:
        active = self._active_workers

        # 1. NO_API_MODE guard — fail closed if guard is unavailable
        if _guard.evaluate(self._no_api_mode_raw):
            return GovernorDecision(False, "BLOCKED_NO_API_MODE", active_workers=active)

        # 2. Emergency kill switch
        if self._policy.emergency_kill_switch:
            return GovernorDecision(False, "BLOCKED_KILL_SWITCH", active_workers=active)

        # 3. Provider-error stop
        if self._provider_error_stop:
            return GovernorDecision(
                False, "BLOCKED_PROVIDER_ERROR_STOP", active_workers=active
            )

        # 4. Paid execution must be explicitly enabled
        if not self._policy.paid_execution_enabled:
            return GovernorDecision(
                False, "BLOCKED_PAID_EXECUTION_DISABLED", active_workers=active
            )

        # 5. Provider must be in the explicit allowlist
        if request.provider not in self._policy.provider_allowlist:
            return GovernorDecision(
                False, "BLOCKED_PROVIDER_NOT_ALLOWED", active_workers=active
            )

        # 6. Retry limit
        if request.retry_count > self._policy.max_retries:
            return GovernorDecision(
                False, "BLOCKED_RETRY_LIMIT_EXCEEDED", active_workers=active
            )

        # 7. Concurrency limit
        if self._active_workers >= self._policy.paid_worker_concurrency:
            return GovernorDecision(
                False, "BLOCKED_CONCURRENCY_LIMIT", active_workers=active
            )

        # 8–10. Budget checks (when stop_on_budget_threshold is True)
        if self._policy.stop_on_budget_threshold:
            estimated = request.estimated_cost_usd or Decimal(0)
            now = datetime.now(timezone.utc)

            if self._policy.per_run_budget is not None:
                if estimated > self._policy.per_run_budget:
                    return GovernorDecision(
                        False, "BLOCKED_PER_RUN_BUDGET_EXCEEDED", active_workers=active
                    )

            if self._policy.daily_budget is not None:
                daily_spent = self._daily_spent(now)
                if daily_spent + estimated > self._policy.daily_budget:
                    return GovernorDecision(
                        False, "BLOCKED_DAILY_BUDGET_EXCEEDED", active_workers=active
                    )

            if self._policy.monthly_budget is not None:
                monthly_spent = self._monthly_spent(now)
                if monthly_spent + estimated > self._policy.monthly_budget:
                    return GovernorDecision(
                        False, "BLOCKED_MONTHLY_BUDGET_EXCEEDED", active_workers=active
                    )

        return GovernorDecision(
            True, "AUTHORIZED", provider=request.provider, active_workers=active
        )

    def _daily_spent(self, now: datetime) -> Decimal:
        today = now.date()
        total = Decimal(0)
        for e in self._ledger._entries.values():
            if e.started_at.date() == today and e.estimated_cost_usd is not None:
                total += e.estimated_cost_usd
        return total

    def _monthly_spent(self, now: datetime) -> Decimal:
        total = Decimal(0)
        for e in self._ledger._entries.values():
            if (
                e.started_at.year == now.year
                and e.started_at.month == now.month
                and e.estimated_cost_usd is not None
            ):
                total += e.estimated_cost_usd
        return total
