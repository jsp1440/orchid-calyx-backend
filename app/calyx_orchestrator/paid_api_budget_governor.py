"""Paid API Budget Governor — thread-safe $50 hard ceiling with pre-reservation.

NEVER auto-reloads. Reserve BEFORE every provider call. No call proceeds
unless a reservation is held. Actual cost confirmed/released after the call.

Usage:
    governor = PaidAPIBudgetGovernor()  # $50 hard ceiling
    rsv = governor.reserve("task-key", estimated_usd=0.02)
    try:
        result = provider.call(...)
        receipt = governor.confirm(rsv.reservation_id, actual_usd=result.cost_usd)
    except Exception:
        governor.release_reservation(rsv.reservation_id)
        raise
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


HARD_CEILING_USD: float = 50.0  # immutable program ceiling; no auto-reload


class BudgetExhaustedError(RuntimeError):
    """Raised when a reservation would push committed spend past the hard ceiling."""


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    """Pre-reservation made before an API call. Hold until confirm or release."""

    reservation_id: str
    task_key: str
    estimated_usd: float
    reserved_at: str
    provider_hint: str


@dataclass(frozen=True, slots=True)
class BudgetReceipt:
    """Confirmed cost record after an API call completes."""

    reservation_id: str
    task_key: str
    run_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_usd: float
    actual_usd: float
    confirmed_at: str

    def ledger_line(self) -> str:
        """Machine-readable line for the SWARM-GOVERNOR-LEDGER (#1330)."""
        date = self.confirmed_at[:10]
        month = self.confirmed_at[:7]
        return (
            f"[OC-GOVERNOR-COST] run_id={self.run_id} "
            f"task={self.task_key} "
            f"provider={self.provider} model={self.model} "
            f"input_tokens={self.input_tokens} output_tokens={self.output_tokens} "
            f"reserved_usd={self.estimated_usd:.6f} actual_usd={self.actual_usd:.6f} "
            f"date={date} month={month}"
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "run_id": self.run_id,
            "task_key": self.task_key,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": self.estimated_usd,
            "actual_usd": self.actual_usd,
            "confirmed_at": self.confirmed_at,
        }


class PaidAPIBudgetGovernor:
    """Thread-safe paid API budget governor.

    Enforces a hard ceiling (default $50.00) across concurrent executions.
    Reserves budget BEFORE each API call; confirms actual cost after.
    NO auto-reload — the ceiling is immutable for the governor's lifetime.

    Thread safety: all mutating operations are serialised by a single lock.
    """

    def __init__(
        self,
        ceiling_usd: float = HARD_CEILING_USD,
        governor_id: str | None = None,
    ) -> None:
        if ceiling_usd <= 0:
            raise ValueError("BUDGET_CEILING_MUST_BE_POSITIVE")
        if ceiling_usd > HARD_CEILING_USD:
            raise ValueError(
                f"BUDGET_CEILING_EXCEEDS_PROGRAM_LIMIT: "
                f"{ceiling_usd} > {HARD_CEILING_USD}"
            )
        self._ceiling = ceiling_usd
        self._governor_id = governor_id or f"gov-{uuid.uuid4().hex[:8]}"
        self._spent_usd: float = 0.0
        self._reserved_usd: float = 0.0
        self._reservations: dict[str, BudgetReservation] = {}
        self._receipts: list[BudgetReceipt] = []
        self._lock = threading.Lock()

    @property
    def ceiling_usd(self) -> float:
        return self._ceiling

    @property
    def spent_usd(self) -> float:
        with self._lock:
            return self._spent_usd

    @property
    def reserved_usd(self) -> float:
        with self._lock:
            return self._reserved_usd

    @property
    def committed_usd(self) -> float:
        with self._lock:
            return self._spent_usd + self._reserved_usd

    @property
    def available_usd(self) -> float:
        with self._lock:
            return self._ceiling - (self._spent_usd + self._reserved_usd)

    def reserve(
        self,
        task_key: str,
        estimated_usd: float,
        provider_hint: str = "",
    ) -> BudgetReservation:
        """Reserve budget before an API call. Raises BudgetExhaustedError if ceiling would be exceeded."""
        if estimated_usd <= 0:
            raise ValueError("BUDGET_RESERVATION_MUST_BE_POSITIVE")
        with self._lock:
            committed = self._spent_usd + self._reserved_usd
            if committed + estimated_usd > self._ceiling:
                raise BudgetExhaustedError(
                    f"BUDGET_CEILING_REACHED: committed=${committed:.4f} "
                    f"+ reservation=${estimated_usd:.4f} would exceed "
                    f"ceiling=${self._ceiling:.2f}. "
                    f"No auto-reload. Paid dispatch halted."
                )
            rsv = BudgetReservation(
                reservation_id=f"rsv-{uuid.uuid4().hex}",
                task_key=task_key,
                estimated_usd=estimated_usd,
                reserved_at=datetime.now(timezone.utc).isoformat(),
                provider_hint=provider_hint,
            )
            self._reservations[rsv.reservation_id] = rsv
            self._reserved_usd += estimated_usd
            return rsv

    def confirm(
        self,
        reservation_id: str,
        *,
        actual_usd: float,
        run_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> BudgetReceipt:
        """Confirm actual spend after an API call. Releases reservation; records receipt."""
        with self._lock:
            rsv = self._reservations.pop(reservation_id, None)
            if rsv is None:
                raise LookupError(
                    f"BUDGET_RESERVATION_NOT_FOUND: {reservation_id}"
                )
            self._reserved_usd -= rsv.estimated_usd
            self._spent_usd += actual_usd
            receipt = BudgetReceipt(
                reservation_id=reservation_id,
                task_key=rsv.task_key,
                run_id=run_id,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_usd=rsv.estimated_usd,
                actual_usd=actual_usd,
                confirmed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._receipts.append(receipt)
            return receipt

    def release_reservation(self, reservation_id: str) -> None:
        """Release a reservation without spending (API call was skipped or failed before call)."""
        with self._lock:
            rsv = self._reservations.pop(reservation_id, None)
            if rsv is not None:
                self._reserved_usd -= rsv.estimated_usd

    def all_receipts(self) -> list[BudgetReceipt]:
        with self._lock:
            return list(self._receipts)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "governor_id": self._governor_id,
                "ceiling_usd": self._ceiling,
                "spent_usd": self._spent_usd,
                "reserved_usd": self._reserved_usd,
                "committed_usd": self._spent_usd + self._reserved_usd,
                "available_usd": self._ceiling - (self._spent_usd + self._reserved_usd),
                "open_reservations": len(self._reservations),
                "confirmed_receipts": len(self._receipts),
                "auto_reload": False,
            }
