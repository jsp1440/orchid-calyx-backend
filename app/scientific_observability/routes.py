"""Read-only query boundary for scientific observability.

Exposes trace reconstruction, event queries, and readiness — all read-only and
advisory. Nothing here mutates authoritative scientific state, publishes, or
grants authority. Producers write events through
``ObservabilityService.record`` (not via HTTP), keeping the append-only
guarantee inside the backend boundary.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from .service import ObservabilityService
from .store import get_default_store

router = APIRouter(prefix="/api/scientific-observability", tags=["SCI-OBS-001"])

CONTRACT_VERSION = "sci-obs-api-v1"


def _service() -> ObservabilityService:
    return ObservabilityService(get_default_store())


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "governance": {
            "read_only": True,
            "does_not_publish": True,
            "does_not_grant_scientific_authority": True,
        },
        **payload,
    }


@router.get("/trace/{correlation_id}")
def get_trace(correlation_id: str) -> dict[str, Any]:
    """Reconstruct an ordered trace from immutable events for a correlation id."""

    events = _service().reconstruct_trace(correlation_id)
    return _envelope(
        {
            "correlation_id": correlation_id,
            "event_count": len(events),
            "events": events,
            "reconstructable": bool(events),
        }
    )


@router.get("/events")
def query_events(
    correlation_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    accepted_name: str | None = Query(default=None),
    safe_status: str | None = Query(default=None),
) -> dict[str, Any]:
    events = get_default_store().query(
        correlation_id=correlation_id,
        event_type=event_type,
        accepted_name=accepted_name,
        safe_status=safe_status,
    )
    return _envelope({"event_count": len(events), "events": events})
