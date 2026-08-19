"""Read-only activation preflight for the governed Vision-Lexicon subsystem.

The preflight reports persistence/schema readiness independently from live
provider readiness. It never applies migrations, changes environment flags,
or invokes an inference provider.
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.multimodal_intelligence.vision_provider_registry import provider_readiness

from . import activation


def _build_preflight(
    *,
    database_url_configured: bool,
    connectivity: bool,
    schema_problem: str | None,
    durable_requested: bool,
    provider_status: str,
    live_inference_enabled: bool,
    inspection_error: str | None = None,
    provider_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema_ready = connectivity and schema_problem is None and inspection_error is None
    persistence_activation_ready = database_url_configured and connectivity and schema_ready
    persistence_active = durable_requested and persistence_activation_ready
    provider_ready = provider_status == "READY"
    live_inference_activation_ready = persistence_active and provider_ready and live_inference_enabled

    blockers: list[str] = []
    if not database_url_configured:
        blockers.append("VISION_DATABASE_URL_NOT_CONFIGURED")
    elif not connectivity:
        blockers.append("VISION_DATABASE_UNREACHABLE")
    elif inspection_error:
        blockers.append("VISION_SCHEMA_INSPECTION_FAILED")
    if schema_problem:
        blockers.append(schema_problem)
    if not durable_requested:
        blockers.append("VISION_DURABLE_PERSISTENCE_DISABLED")
    if provider_status == "PROVIDER_NOT_CONFIGURED":
        blockers.append("VISION_PROVIDER_NOT_CONFIGURED")
    elif provider_status == "PERSISTENCE_NOT_READY":
        blockers.append("VISION_PROVIDER_PERSISTENCE_NOT_READY")
    elif provider_status != "READY":
        blockers.append(f"VISION_{provider_status}")
    if not live_inference_enabled:
        blockers.append("VISION_LIVE_INFERENCE_DISABLED")

    provider = dict(provider_details or {})
    provider.pop("live_inference_enabled", None)
    provider.pop("provider_status", None)

    return {
        "schema_version": "vision-activation-preflight/v2",
        "read_only": True,
        "mutations_performed": False,
        "database_url_configured": database_url_configured,
        "connectivity": connectivity,
        "schema_ready": schema_ready,
        "schema_problem": schema_problem,
        "inspection_error": inspection_error,
        "durable_requested": durable_requested,
        "persistence_activation_ready": persistence_activation_ready,
        "persistence_active": persistence_active,
        "provider_status": provider_status,
        "provider_ready": provider_ready,
        "provider": provider,
        "live_inference_enabled": live_inference_enabled,
        "live_inference_activation_ready": live_inference_activation_ready,
        "blockers": blockers,
        "activation_order": [
            "activate and verify oc_vision schema",
            "enable governed durable Vision persistence",
            "select an explicitly registered canonical VisionProvider adapter",
            "verify that adapter with a side-effect-free readiness probe",
            "enable live inference only after provider validation",
            "retain human review before Matrix scoring or knowledge promotion",
        ],
    }


def vision_activation_preflight() -> dict[str, Any]:
    """Inspect Vision activation prerequisites without changing runtime state."""
    durable = activation.durable_requested()
    provider = provider_readiness()
    provider_status = str(provider.get("provider_status") or "PROVIDER_NOT_CONFIGURED")
    live_inference = bool(provider.get("live_inference_enabled"))

    common = {
        "durable_requested": durable,
        "provider_status": provider_status,
        "live_inference_enabled": live_inference,
        "provider_details": provider,
    }

    try:
        database_url = activation._postgres_url()
    except (RuntimeError, ValueError, OSError) as exc:
        return _build_preflight(
            database_url_configured=False,
            connectivity=False,
            schema_problem=None,
            inspection_error=str(exc),
            **common,
        )

    try:
        conn = psycopg.connect(
            database_url,
            connect_timeout=activation._SCHEMA_PROBE_CONNECT_TIMEOUT_SECONDS,
        )
    except (psycopg.Error, RuntimeError, ValueError, OSError) as exc:
        return _build_preflight(
            database_url_configured=True,
            connectivity=False,
            schema_problem=None,
            inspection_error=str(exc),
            **common,
        )

    try:
        with conn, conn.cursor() as cur:
            problem = activation._schema_problem(cur)
    except (psycopg.Error, RuntimeError, ValueError, OSError) as exc:
        return _build_preflight(
            database_url_configured=True,
            connectivity=True,
            schema_problem=None,
            inspection_error=str(exc),
            **common,
        )

    return _build_preflight(
        database_url_configured=True,
        connectivity=True,
        schema_problem=problem,
        **common,
    )
