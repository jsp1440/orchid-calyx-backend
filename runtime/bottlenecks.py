from __future__ import annotations

from .models import HealthCheckResult


class BottleneckService:
    """Ranks current bottlenecks from health and runtime evidence."""

    def detect(self, health: list[HealthCheckResult]) -> str:
        if not health:
            return "Missing configuration or visibility: no health checks reported."

        critical = [h for h in health if h.status == "critical"]
        unknown = [h for h in health if h.status == "unknown"]
        warning = [h for h in health if h.status == "warning"]

        if critical:
            critical_items = "; ".join(
                f"{h.component} — {h.message}" for h in critical
            )
            return f"Critical service failure: {critical_items}"

        if unknown:
            unknown_components = ", ".join(h.component for h in unknown)
            return f"Missing configuration or visibility: {unknown_components}"

        if warning:
            warning_items = "; ".join(
                f"{h.component} — {h.message}" for h in warning
            )
            return f"Degraded service: {warning_items}"

        return f"No critical operational bottleneck detected across {len(health)} health checks."
