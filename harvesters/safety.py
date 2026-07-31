"""BUILD-105 bounded safety controls for production harvesters.

These controls wrap the mature BUILD-093 harvesters without replacing their
source-specific logic. They are dependency-light and safe to import in worker,
API, and offline test contexts.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


class BudgetExceeded(RuntimeError):
    pass


class CircuitOpen(RuntimeError):
    pass


class CursorRegression(RuntimeError):
    pass


@dataclass
class WorkBudget:
    max_runtime_seconds: float = 300.0
    max_requests: int = 100
    max_records: int = 10_000
    max_db_writes: int = 5_000
    started_monotonic: float = field(default_factory=time.monotonic)
    requests: int = 0
    records: int = 0
    db_writes: int = 0

    def check(self) -> None:
        elapsed = time.monotonic() - self.started_monotonic
        if elapsed > self.max_runtime_seconds:
            raise BudgetExceeded("runtime limit reached")
        if self.requests > self.max_requests:
            raise BudgetExceeded("request limit reached")
        if self.records > self.max_records:
            raise BudgetExceeded("record limit reached")
        if self.db_writes > self.max_db_writes:
            raise BudgetExceeded("database write limit reached")

    def add_requests(self, value: int = 1) -> None:
        self.requests += max(0, int(value or 0))
        self.check()

    def add_records(self, value: int = 1) -> None:
        self.records += max(0, int(value or 0))
        self.check()

    def add_writes(self, value: int = 1) -> None:
        self.db_writes += max(0, int(value or 0))
        self.check()

    def snapshot(self) -> dict[str, Any]:
        return {
            "runtime_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "requests": self.requests,
            "records": self.records,
            "db_writes": self.db_writes,
            "limits": {
                "runtime_seconds": self.max_runtime_seconds,
                "requests": self.max_requests,
                "records": self.max_records,
                "db_writes": self.max_db_writes,
            },
        }


@dataclass
class CircuitBreaker:
    empty_threshold: int = 3
    failure_rate_threshold: float = 1.0
    consecutive_empty_pages: int = 0
    open_reason: str | None = None

    @property
    def is_open(self) -> bool:
        return self.open_reason is not None

    def check(self) -> None:
        if self.is_open:
            raise CircuitOpen(self.open_reason or "circuit open")

    def record_page(self, *, is_empty: bool, failure_rate: float = 0.0,
                    had_attempts: bool = False) -> None:
        if is_empty:
            self.consecutive_empty_pages += 1
        else:
            self.consecutive_empty_pages = 0
        if self.consecutive_empty_pages >= self.empty_threshold:
            self.open_reason = f"{self.consecutive_empty_pages} consecutive empty pages"
        elif had_attempts and failure_rate >= self.failure_rate_threshold:
            self.open_reason = f"failure rate {failure_rate:.3f} reached threshold"

    def reset(self) -> None:
        self.consecutive_empty_pages = 0
        self.open_reason = None


@dataclass
class CursorGuard:
    allow_equal: bool = True
    previous: Any = None

    def validate(self, candidate: Any) -> Any:
        if candidate is None:
            return self.previous
        if self.previous is None:
            self.previous = candidate
            return candidate
        try:
            went_backwards = candidate < self.previous
            stayed_equal = candidate == self.previous
        except TypeError:
            went_backwards = str(candidate) < str(self.previous)
            stayed_equal = str(candidate) == str(self.previous)
        if went_backwards or (stayed_equal and not self.allow_equal):
            raise CursorRegression(f"cursor moved from {self.previous!r} to {candidate!r}")
        self.previous = candidate
        return candidate


@dataclass
class RepeatedPageDetector:
    previous_fingerprint: str | None = None

    @staticmethod
    def fingerprint(records: Iterable[Any]) -> str:
        payload = json.dumps(list(records), sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def is_repeat(self, records: Iterable[Any]) -> bool:
        fingerprint = self.fingerprint(records)
        repeated = self.previous_fingerprint == fingerprint
        self.previous_fingerprint = fingerprint
        return repeated


def enforce_gbif_offset(offset: int, limit: int, ceiling: int = 100_000) -> None:
    """Reject GBIF offset paging that reaches its documented 100k window."""
    if int(offset or 0) + int(limit or 0) > ceiling:
        raise BudgetExceeded(
            f"GBIF offset window exhausted: offset={offset}, limit={limit}, ceiling={ceiling}"
        )
