"""Wall-clock deadline for one paid provider call, and the lease it implies.

httpx timeouts are per phase (connect, write, pool, and every individual
read), so a server that drips bytes can hold a "60 second" request open far
longer than 60 seconds. A ledger lease that is shorter than the real call
lets a second worker take the lease over and pay again for the same
resource.

:func:`call_with_deadline` bounds the CALLER's wall-clock: the call runs on a
daemon thread and the caller stops waiting at the deadline, raising
:class:`PaidCallDeadlineExceeded`. The abandoned thread's eventual result is
discarded (never cached, never handed on). The provider may still bill that
one abandoned call; what the deadline guarantees is that the caller resolves
its lease (``fail``) while the lease is still live, so nobody else is
authorised to pay for the resource in the meantime.

:func:`lease_seconds_for` derives the lease from the deadline, so the lease
always outlives the paid call by an explicit margin.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import TypeVar

__all__ = [
    "DEFAULT_LEASE_MARGIN_SECONDS",
    "MAX_PAID_CALL_SECONDS",
    "PaidCallDeadlineExceeded",
    "call_with_deadline",
    "lease_seconds_for",
    "validate_deadline",
]

T = TypeVar("T")

#: Time a lease must outlive the paid call's deadline: the ledger write that
#: settles the lease, and scheduling jitter, happen inside it.
DEFAULT_LEASE_MARGIN_SECONDS = 60

#: Upper bound on any single paid call's wall-clock deadline.
MAX_PAID_CALL_SECONDS = 900.0


class PaidCallDeadlineExceeded(TimeoutError):
    """The paid call did not return within its wall-clock deadline.

    The outcome is unknown to the caller (the provider may or may not have
    completed and billed it); the result, if any, is discarded.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        super().__init__(f"paid provider call exceeded its {seconds:g}s deadline")


def validate_deadline(seconds: object) -> float:
    """Return ``seconds`` as a float, or raise (fail closed)."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise TypeError("paid call deadline must be a number of seconds")
    value = float(seconds)
    if not math.isfinite(value) or value <= 0 or value > MAX_PAID_CALL_SECONDS:
        raise ValueError(
            f"paid call deadline must be in (0, {MAX_PAID_CALL_SECONDS:g}] seconds"
        )
    return value


def lease_seconds_for(
    deadline_seconds: float, *, margin_seconds: int = DEFAULT_LEASE_MARGIN_SECONDS
) -> int:
    """Lease duration strictly longer than ``deadline_seconds`` plus a margin."""
    deadline = validate_deadline(deadline_seconds)
    if isinstance(margin_seconds, bool) or not isinstance(margin_seconds, int):
        raise TypeError("lease margin must be an integer number of seconds")
    if margin_seconds < 1:
        raise ValueError("lease margin must be at least one second")
    return math.ceil(deadline) + margin_seconds


def call_with_deadline(fn: Callable[[], T], seconds: float) -> T:
    """Run ``fn()`` and return its result, or raise at ``seconds`` wall-clock.

    Exceptions raised by ``fn`` propagate unchanged.
    """
    deadline = validate_deadline(seconds)
    outcome: dict[str, object] = {}
    done = threading.Event()

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            outcome["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=target, name="paid-call-deadline", daemon=True)
    worker.start()
    if not done.wait(deadline):
        raise PaidCallDeadlineExceeded(deadline)
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["value"]  # type: ignore[return-value]
