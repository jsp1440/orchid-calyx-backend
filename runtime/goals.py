from __future__ import annotations


class GoalPlannerService:
    """Selects the single recommended next goal."""

    def plan(self, bottleneck: str) -> str:
        if "Critical service failure" in bottleneck:
            return "Restore failed service and rerun health checks."

        if "Missing configuration" in bottleneck:
            return "Configure missing runtime environment variables and rerun health checks."

        return "Convert HealthMonitorService into a backend API endpoint and display it in Mission Control."
