from datetime import datetime, timedelta, timezone

import pytest

from app.canonical_brain.leases import ExecutionLeaseManager
from app.canonical_brain.orchestration import BuildAssignment


def _assignment(status: str = "scheduled") -> BuildAssignment:
    return BuildAssignment(
        assignment_id="a" * 64,
        build_id="BUILD-BRAIN-109",
        agent_id="agent:brain-engineer",
        architecture_id="architecture:brain",
        assigned_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        status=status,
    )


def test_lease_acquisition_is_idempotent_for_same_worker() -> None:
    manager = ExecutionLeaseManager(lease_seconds=60)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    first = manager.acquire(_assignment(), "worker-1", now)
    second = manager.acquire(_assignment(), "worker-1", now)
    assert first == second


def test_duplicate_active_worker_is_rejected() -> None:
    manager = ExecutionLeaseManager(lease_seconds=60)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    manager.acquire(_assignment(), "worker-1", now)
    with pytest.raises(ValueError, match="active worker lease"):
        manager.acquire(_assignment(), "worker-2", now + timedelta(seconds=1))


def test_heartbeat_extends_lease_and_requires_owner() -> None:
    manager = ExecutionLeaseManager(lease_seconds=60)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    lease = manager.acquire(_assignment(), "worker-1", now)
    updated = manager.heartbeat(lease.lease_id, "worker-1", now + timedelta(seconds=30))
    assert updated.expires_at == now + timedelta(seconds=90)
    with pytest.raises(ValueError, match="does not own"):
        manager.heartbeat(lease.lease_id, "worker-2", now + timedelta(seconds=31))


def test_expired_lease_becomes_retry_candidate() -> None:
    manager = ExecutionLeaseManager(lease_seconds=60, max_attempts=3)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    lease = manager.acquire(_assignment(), "worker-1", now, attempt=1)
    decision = manager.recovery_decision(lease.lease_id, now + timedelta(seconds=61))
    assert decision.action == "retry_candidate"
    assert decision.retry_attempt == 2


def test_retry_limit_requires_manual_review() -> None:
    manager = ExecutionLeaseManager(lease_seconds=60, max_attempts=2)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    lease = manager.acquire(_assignment(), "worker-1", now, attempt=2)
    decision = manager.recovery_decision(lease.lease_id, now + timedelta(seconds=61))
    assert decision.action == "manual_review"


def test_cancellation_receipt_is_deterministic() -> None:
    manager = ExecutionLeaseManager(lease_seconds=60)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    lease = manager.acquire(_assignment(), "worker-1", now)
    receipt = manager.cancel(
        lease.lease_id,
        "worker-1",
        now + timedelta(seconds=5),
        "operator stop",
    )
    assert receipt.assignment_id == lease.assignment_id
    assert manager.leases()[0].status == "cancelled"


def test_naive_timestamps_fail_closed() -> None:
    manager = ExecutionLeaseManager()
    with pytest.raises(ValueError, match="timezone-aware"):
        naive_timestamp = datetime(2026, 8, 6, tzinfo=timezone.utc).replace(tzinfo=None)
        manager.acquire(_assignment(), "worker-1", naive_timestamp)
