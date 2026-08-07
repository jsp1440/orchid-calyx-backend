from datetime import datetime, timezone

import pytest

from app.canonical_brain.executor import DeterministicDryRunExecutor, ExecutionRequest
from app.canonical_brain.orchestration import BuildAssignment


def assignment(status: str = "running") -> BuildAssignment:
    return BuildAssignment(
        assignment_id="a" * 64,
        build_id="BUILD-BRAIN-108",
        agent_id="agent:brain-engineer",
        architecture_id="architecture:brain",
        assigned_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        status=status,
    )


def test_dry_run_executor_is_deterministic_non_authoritative_preflight() -> None:
    executor = DeterministicDryRunExecutor({"brain.executor.dry-run"})
    request = ExecutionRequest(
        assignment=assignment(),
        capability="brain.executor.dry-run",
        input_payload={"b": 2, "a": 1},
        evidence_uris=["brain://builds/108", "brain://builds/108"],
        recorded_at=datetime(2026, 8, 6, 19, 30, tzinfo=timezone.utc),
    )
    first = executor.execute(request)
    second = executor.execute(request)
    assert first == second
    assert first.dry_run is True
    assert first.authoritative is False
    assert first.state == "delivered"
    assert first.outcome == "DELIVERED"
    assert first.evidence_uris == ["brain://builds/108"]
    assert first.output["mode"] == "dry_run"
    assert first.output["side_effects"] == []
    assert len(first.input_checksum) == 64
    assert len(first.output_checksum) == 64


def test_executor_rejects_unsupported_capability() -> None:
    executor = DeterministicDryRunExecutor({"brain.executor.dry-run"})
    with pytest.raises(ValueError, match="unsupported executor capability"):
        executor.execute(
            ExecutionRequest(
                assignment=assignment(),
                capability="shell.execute",
                input_payload={},
                evidence_uris=["brain://builds/108"],
                recorded_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
            )
        )


def test_executor_requires_running_assignment() -> None:
    executor = DeterministicDryRunExecutor({"brain.executor.dry-run"})
    with pytest.raises(ValueError, match="must be running"):
        executor.execute(
            ExecutionRequest(
                assignment=assignment("scheduled"),
                capability="brain.executor.dry-run",
                input_payload={},
                evidence_uris=["brain://builds/108"],
                recorded_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
            )
        )
