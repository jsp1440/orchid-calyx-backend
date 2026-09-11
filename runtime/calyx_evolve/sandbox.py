"""Bounded, staging-only execution context for candidate reconciliation.

The sandbox is the only thing a candidate strategy is handed.  It owns the
resource bounds (wall-clock deadline, record cap) and it owns the refusal of the
capabilities candidates must never have: production writes, taxonomy activation,
Knowledge Graph publication, and outbound network publication.

Those refusals are real methods that raise, not documentation.  If a future
generator learns to ask for them, it gets an exception and a terminal
``rejected_unsafe`` record — not a side effect.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SCOPE_STAGING_ONLY = "STAGING_ONLY"

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RECORDS = 10_000


class SandboxViolation(RuntimeError):
    """Raised when candidate execution attempts a forbidden capability."""


class SandboxTimeout(RuntimeError):
    """Raised when candidate execution exceeds its wall-clock bound."""


class SandboxLimitExceeded(RuntimeError):
    """Raised when candidate execution exceeds its record bound."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_records: int = DEFAULT_MAX_RECORDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_records": self.max_records,
        }


@dataclass
class ExperimentSandbox:
    """A single-use bounded execution context."""

    limits: SandboxLimits = field(default_factory=SandboxLimits)
    scope: str = SCOPE_STAGING_ONLY
    monotonic: Callable[[], float] = time.monotonic
    _started_at: float | None = field(default=None, init=False, repr=False)
    _records: int = field(default=0, init=False, repr=False)

    def start(self) -> ExperimentSandbox:
        if self.scope != SCOPE_STAGING_ONLY:
            raise SandboxViolation(f"sandbox scope {self.scope!r} is not {SCOPE_STAGING_ONLY}")
        self._started_at = self.monotonic()
        self._records = 0
        return self

    @property
    def started(self) -> bool:
        return self._started_at is not None

    @property
    def records_processed(self) -> int:
        return self._records

    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self.monotonic() - self._started_at)

    def checkpoint(self) -> None:
        """Charge one record against the bounds; raise when either is exceeded."""

        if self._started_at is None:
            raise SandboxViolation("sandbox used before start()")
        self._records += 1
        if self._records > self.limits.max_records:
            raise SandboxLimitExceeded(
                f"candidate processed more than {self.limits.max_records} records"
            )
        if self.elapsed_seconds() > self.limits.timeout_seconds:
            raise SandboxTimeout(
                f"candidate exceeded {self.limits.timeout_seconds} seconds"
            )

    # --- capabilities the sandbox exists to refuse ---------------------------

    def request_production_write(self, *_args: Any, **_kwargs: Any) -> None:
        raise SandboxViolation(
            "production database and Knowledge Graph writes are unavailable in the evolve sandbox"
        )

    def request_taxonomy_activation(self, *_args: Any, **_kwargs: Any) -> None:
        raise SandboxViolation(
            "taxonomy activation is unavailable in the evolve sandbox; "
            "activation requires human scientific review"
        )

    def request_knowledge_graph_publication(self, *_args: Any, **_kwargs: Any) -> None:
        raise SandboxViolation(
            "Knowledge Graph publication is unavailable in the evolve sandbox"
        )

    def request_external_publication(self, *_args: Any, **_kwargs: Any) -> None:
        raise SandboxViolation(
            "external submission and publication are unavailable in the evolve sandbox"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "limits": self.limits.to_dict(),
            "records_processed": self._records,
        }
