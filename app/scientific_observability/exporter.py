"""Vendor-neutral exporter boundary (OpenTelemetry-concept compatible).

Disabled by default and NOT required for the vertical proof. Adds no
OpenTelemetry dependency. The mapping is intentionally OTel-shaped so a future
adapter can forward spans without changing producers:

    trace_id  <- correlation_id
    span_id   <- event_id
    parent    <- parent_event_id
    name      <- event_type

Export is gated by ``SCI_OBS_EXPORT_ENABLED`` (default off). When disabled,
``export`` is a no-op that returns ``0``. Only already-redacted event dicts are
ever handed to this boundary.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable

EXPORT_ENABLED_ENV = "SCI_OBS_EXPORT_ENABLED"


def export_enabled() -> bool:
    return os.environ.get(EXPORT_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def to_otel_span(event: dict[str, Any]) -> dict[str, Any]:
    """Map a redacted observation event to an OTel-shaped span dict."""

    safe = event.get("safe_status") or {}
    return {
        "trace_id": event.get("correlation_id"),
        "span_id": event.get("event_id"),
        "parent_span_id": event.get("parent_event_id"),
        "name": event.get("event_type"),
        "start_time": event.get("occurred_at"),
        "end_time": event.get("recorded_at"),
        "status": safe.get("status"),
        "attributes": {
            "sci_obs.stage": (event.get("pipeline") or {}).get("stage"),
            "sci_obs.component": (event.get("pipeline") or {}).get("component"),
            "sci_obs.reason_code": safe.get("reason_code"),
            "sci_obs.accepted_name": (event.get("taxon") or {}).get("accepted_name"),
        },
    }


def export(
    events: Iterable[dict[str, Any]],
    sink: Callable[[list[dict[str, Any]]], None] | None = None,
) -> int:
    """Export events as OTel-shaped spans. No-op unless explicitly enabled.

    Returns the number of spans exported. When disabled, returns ``0`` and does
    nothing — the proof never depends on export.
    """

    if not export_enabled():
        return 0
    spans = [to_otel_span(e) for e in events]
    if sink is not None:
        sink(spans)
    return len(spans)
