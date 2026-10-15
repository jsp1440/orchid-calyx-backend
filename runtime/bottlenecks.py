from __future__ import annotations

from .models import HealthCheckResult


class BottleneckService:
    """Ranks current bottlenecks from health and runtime evidence."""

    def detect(self, health: list[HealthCheckResult]) -> str:
        critical = [h for h in health if h.status == "critical"]
        unknown = [h for h in health if h.status == "unknown"]

        if critical:
            # Join all critical checks with semicolon separator
            critical_items = [f"{h.component} — {h.message}" for h in critical]
            return f"Critical service failure: {'; '.join(critical_items)}"

        if unknown:
            # Join all unknown components with comma separator
            unknown_items = [h.component for h in unknown]
            return f"Missing configuration or visibility: {', '.join(unknown_items)}"

        if not health:
            return "Missing configuration or visibility: no health checks reported."

        return f"No critical operational bottleneck detected across {len(health)} health checks."
