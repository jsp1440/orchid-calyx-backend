from __future__ import annotations


class GoalPlannerService:
    """Selects the single recommended next goal."""

    def plan(self, bottleneck: str) -> str:
        if bottleneck.startswith("Critical service failure: "):
            return "Restore failed service and rerun health checks."

        if bottleneck == "Missing configuration or visibility: no health checks reported.":
            return "Run the health checks; none were reported."

        if bottleneck.startswith("Missing configuration or visibility: "):
            return "Configure missing runtime environment variables and rerun health checks."

        if bottleneck.startswith("No critical operational bottleneck detected"):
            return "No corrective goal; all health checks passed. Continue monitoring."

        return "Investigate unrecognized bottleneck report and rerun health checks."
