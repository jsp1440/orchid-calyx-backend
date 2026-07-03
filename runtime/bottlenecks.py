from __future__ import annotations
from typing import List
from .models import HealthCheckResult


class BottleneckService:
    """Ranks current bottlenecks from health and runtime evidence."""

    def detect(self, health: List[HealthCheckResult]) -> str:
        critical = [h for h in health if h.status == "critical"]
        unknown = [h for h in health if h.status == "unknown"]

        if critical:
            return f"Critical service failure: {critical[0].component} — {critical[0].message}"

        if unknown:
            return f"Missing configuration or visibility: {unknown[0].component}"

        return "No critical operational bottleneck detected. Next bottleneck is live CDS integration."
