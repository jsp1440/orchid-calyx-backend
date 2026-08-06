from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .orchestration import BuildAssignment


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


LeaseStatus = Literal["active", "expired", "released", "cancelled"]
RecoveryAction = Literal["none", "retry_candidate", "manual_review"]


class ExecutionLease(StrictModel):
    lease_id: str = Field(min_length=16)
    assignment_id: str = Field(min_length=16)
    worker_id: str = Field(min_length=3)
    status: LeaseStatus
    acquired_at: datetime
    last_heartbeat_at: datetime
    expires_at: datetime
    attempt: int = Field(default=1, ge=1)


class RecoveryDecision(StrictModel):
    assignment_id: str = Field(min_length=16)
    action: RecoveryAction
    reason: str
    retry_attempt: int | None = Field(default=None, ge=1)


class CancellationReceipt(StrictModel):
    cancellation_id: str = Field(min_length=16)
    assignment_id: str = Field(min_length=16)
    lease_id: str = Field(min_length=16)
    worker_id: str = Field(min_length=3)
    cancelled_at: datetime
    reason: str = Field(min_length=3)


class ExecutionLeaseManager:
    """Coordinates candidate execution ownership without performing execution."""

    def __init__(self, lease_seconds: int = 300, max_attempts: int = 3) -> None:
        if lease_seconds < 1 or max_attempts < 1:
            raise ValueError("lease_seconds and max_attempts must be positive")
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._leases: dict[str, ExecutionLease] = {}
        self._by_assignment: dict[str, str] = {}
        self._cancellations: dict[str, CancellationReceipt] = {}

    @staticmethod
    def _stable_id(*parts: str) -> str:
        return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("lease timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    def acquire(
        self,
        assignment: BuildAssignment,
        worker_id: str,
        acquired_at: datetime,
        attempt: int = 1,
    ) -> ExecutionLease:
        if assignment.status not in {"scheduled", "running"}:
            raise ValueError("only scheduled or running assignments may be leased")
        now = self._utc(acquired_at)
        current_id = self._by_assignment.get(assignment.assignment_id)
        if current_id:
            current = self._leases[current_id]
            if current.status == "active" and current.expires_at > now:
                if current.worker_id != worker_id:
                    raise ValueError("assignment already has an active worker lease")
                return current
        lease_id = self._stable_id(assignment.assignment_id, worker_id, str(attempt))
        lease = ExecutionLease(
            lease_id=lease_id,
            assignment_id=assignment.assignment_id,
            worker_id=worker_id,
            status="active",
            acquired_at=now,
            last_heartbeat_at=now,
            expires_at=now + timedelta(seconds=self._lease_seconds),
            attempt=attempt,
        )
        self._leases[lease_id] = lease
        self._by_assignment[assignment.assignment_id] = lease_id
        return lease

    def heartbeat(self, lease_id: str, worker_id: str, recorded_at: datetime) -> ExecutionLease:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise KeyError(lease_id)
        now = self._utc(recorded_at)
        if lease.worker_id != worker_id:
            raise ValueError("worker does not own this lease")
        if lease.status != "active" or lease.expires_at <= now:
            raise ValueError("expired or inactive leases cannot heartbeat")
        updated = lease.model_copy(
            update={
                "last_heartbeat_at": now,
                "expires_at": now + timedelta(seconds=self._lease_seconds),
            }
        )
        self._leases[lease_id] = updated
        return updated

    def classify(self, lease_id: str, observed_at: datetime) -> ExecutionLease:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise KeyError(lease_id)
        now = self._utc(observed_at)
        if lease.status == "active" and lease.expires_at <= now:
            lease = lease.model_copy(update={"status": "expired"})
            self._leases[lease_id] = lease
        return lease

    def recovery_decision(self, lease_id: str, observed_at: datetime) -> RecoveryDecision:
        lease = self.classify(lease_id, observed_at)
        if lease.status != "expired":
            return RecoveryDecision(
                assignment_id=lease.assignment_id,
                action="none",
                reason="Lease remains active or has already reached a terminal state.",
            )
        next_attempt = lease.attempt + 1
        if next_attempt <= self._max_attempts:
            return RecoveryDecision(
                assignment_id=lease.assignment_id,
                action="retry_candidate",
                reason="Lease expired; candidate work may be safely rescheduled.",
                retry_attempt=next_attempt,
            )
        return RecoveryDecision(
            assignment_id=lease.assignment_id,
            action="manual_review",
            reason="Maximum candidate execution attempts reached.",
        )

    def release(self, lease_id: str, worker_id: str) -> ExecutionLease:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise KeyError(lease_id)
        if lease.worker_id != worker_id:
            raise ValueError("worker does not own this lease")
        if lease.status != "active":
            raise ValueError("only active leases may be released")
        updated = lease.model_copy(update={"status": "released"})
        self._leases[lease_id] = updated
        return updated

    def cancel(
        self,
        lease_id: str,
        worker_id: str,
        cancelled_at: datetime,
        reason: str,
    ) -> CancellationReceipt:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise KeyError(lease_id)
        if lease.worker_id != worker_id:
            raise ValueError("worker does not own this lease")
        if lease.status not in {"active", "expired"}:
            raise ValueError("only active or expired leases may be cancelled")
        now = self._utc(cancelled_at)
        updated = lease.model_copy(update={"status": "cancelled"})
        self._leases[lease_id] = updated
        cancellation_id = self._stable_id(lease.assignment_id, lease_id, "cancelled")
        receipt = CancellationReceipt(
            cancellation_id=cancellation_id,
            assignment_id=lease.assignment_id,
            lease_id=lease_id,
            worker_id=worker_id,
            cancelled_at=now,
            reason=reason,
        )
        existing = self._cancellations.get(cancellation_id)
        if existing and existing != receipt:
            raise ValueError(f"conflicting cancellation receipt identity: {cancellation_id}")
        self._cancellations[cancellation_id] = receipt
        return receipt

    def leases(self) -> list[ExecutionLease]:
        return sorted(self._leases.values(), key=lambda item: item.lease_id)

    def cancellations(self) -> list[CancellationReceipt]:
        return sorted(self._cancellations.values(), key=lambda item: item.cancellation_id)
