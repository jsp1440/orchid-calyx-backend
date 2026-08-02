"""Read-only adapters that normalize live subsystem snapshots into audit signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from runtime.self_audit import AuditSignal


def github_ci_signals(snapshot: Mapping[str, Any]) -> list[AuditSignal]:
    failing = int(snapshot.get("failing_checks", 0) or 0)
    stale = int(snapshot.get("stale_pull_requests", 0) or 0)
    signals = [
        AuditSignal(
            source="github",
            check="ci_checks",
            status="failed" if failing else "healthy",
            severity="high" if failing else "info",
            details={"count": failing, "recommended_action": "prepare_draft_work_item"},
        )
    ]
    if stale:
        signals.append(
            AuditSignal(
                source="github",
                check="stale_pull_requests",
                status="stale",
                severity="medium",
                details={"count": stale, "recommended_action": "prepare_draft_work_item"},
            )
        )
    return signals


def backend_health_signals(snapshot: Mapping[str, Any]) -> list[AuditSignal]:
    healthy = bool(snapshot.get("healthy", False))
    return [
        AuditSignal(
            source="backend",
            check="service_health",
            status="healthy" if healthy else "degraded",
            severity="critical" if not healthy else "info",
            details={"http_status": snapshot.get("http_status")},
        )
    ]


def queue_signals(snapshot: Mapping[str, Any]) -> list[AuditSignal]:
    failed = int(snapshot.get("failed", 0) or 0)
    running = int(snapshot.get("running", 0) or 0)
    stuck = int(snapshot.get("stuck", 0) or 0)
    return [
        AuditSignal(
            source="runtime_queue",
            check="failed_tasks",
            status="failed" if failed else "healthy",
            severity="high" if failed else "info",
            details={"count": failed},
        ),
        AuditSignal(
            source="runtime_queue",
            check="stuck_tasks",
            status="blocked" if stuck else "healthy",
            severity="high" if stuck else "info",
            details={"count": stuck, "running": running},
        ),
    ]


def harvester_signals(snapshot: Mapping[str, Any]) -> list[AuditSignal]:
    stale = int(snapshot.get("stale_sources", 0) or 0)
    errors = int(snapshot.get("errors", 0) or 0)
    return [
        AuditSignal(
            source="harvesters",
            check="source_freshness",
            status="stale" if stale else "healthy",
            severity="medium" if stale else "info",
            details={"count": stale},
        ),
        AuditSignal(
            source="harvesters",
            check="execution_errors",
            status="error" if errors else "healthy",
            severity="high" if errors else "info",
            details={"count": errors},
        ),
    ]
