"""Data models for the Swarm Execution Governor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One governed execution attempt recorded in the ExecutionLedger."""

    entry_id: str
    issue_task_id: str
    provider: str
    worker_lane: str
    started_at: datetime
    retry_count: int
    governing_policy_snapshot: dict[str, Any]
    ended_at: datetime | None = None
    estimated_tokens: int | None = None
    estimated_cost_usd: Decimal | None = None
    termination_reason: str | None = None
    succeeded: bool | None = None  # None = in-flight


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """Parameters for a single governed provider execution attempt."""

    issue_task_id: str
    provider: str
    worker_lane: str
    retry_count: int = 0
    estimated_cost_usd: Decimal | None = None


@dataclass(frozen=True, slots=True)
class GovernorDecision:
    """Result of a stateless policy evaluation."""

    authorized: bool
    reason: str
    provider: str | None = None
    active_workers: int = 0
