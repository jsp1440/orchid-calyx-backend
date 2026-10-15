from __future__ import annotations

from .models import HealthCheckResult


class BottleneckService:
    """Ranks current bottlenecks from health and runtime evidence."""

    def detect(self, health: list[HealthCheckResult]) -> str:
        critical = [h for h in health if h.status == "critical"]
        unknown = [h for h in health if h.status == "unknown"]

        if not health:
            return "Missing configuration or visibility: no health checks reported."

        if critical:
            components = "; ".join(
                f"{h.component} — {h.message}" for h in critical
            )
            return f"Critical service failure: {components}"

        if unknown:
            components = ", ".join(h.component for h in unknown)
            return f"Missing configuration or visibility: {components}"

        return f"No critical operational bottleneck detected across {len(health)} health checks."
