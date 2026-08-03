"""Code-level readiness for every production Knowledge Graph domain."""

from __future__ import annotations

from typing import Any

from .adapters import adapters_by_domain
from .domain_sources import DOMAIN_SOURCES
from .source_registry import registry_by_domain


def full_domain_code_readiness() -> dict[str, Any]:
    adapters = adapters_by_domain()
    sources = registry_by_domain()
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for configured in DOMAIN_SOURCES:
        if configured.domain == "taxonomy":
            rows.append({
                "domain": "taxonomy",
                "configured_status": configured.status,
                "adapter_registered": True,
                "source_projection_registered": True,
                "source_projection_enabled": True,
                "code_ready": True,
                "limitation": None,
            })
            continue

        adapter = adapters.get(configured.domain)
        source = sources.get(configured.domain)
        enabled = bool(source and source.enabled and source.sql)
        code_ready = configured.status == "production" and adapter is not None and enabled
        limitation = None
        if configured.status != "production":
            limitation = "Domain is withheld from production publication."
        elif adapter is None:
            limitation = "No graph adapter is registered."
        elif source is None:
            limitation = "No canonical read-only source projection is registered."
        elif not enabled:
            limitation = source.blocked_reason or "Source projection is disabled."

        if configured.status == "production" and not code_ready:
            blockers.append(f"{configured.domain}:{limitation}")

        rows.append({
            "domain": configured.domain,
            "configured_status": configured.status,
            "adapter_registered": adapter is not None,
            "source_projection_registered": source is not None,
            "source_projection_enabled": enabled,
            "code_ready": code_ready,
            "limitation": limitation,
        })

    return {
        "contract": "calyx-full-domain-code-readiness-v1",
        "domains": rows,
        "blockers": blockers,
        "all_production_domains_code_ready": not blockers,
    }
