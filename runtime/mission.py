from __future__ import annotations
from .models import MissionReport, utc_now, HealthCheckResult, GovernanceReview


class MissionReporterService:
    """Creates the operational briefing for Mission Control."""

    def build_report(
        self,
        health: list[HealthCheckResult],
        bottleneck: str,
        goal: str,
        governance: GovernanceReview,
    ) -> MissionReport:
        if any(h.status == "critical" for h in health):
            overall = "critical"
        elif any(h.status in {"unknown", "warning"} for h in health):
            overall = "attention"
        else:
            overall = "healthy"

        return MissionReport(
            generated_at=utc_now(),
            overall_status=overall,
            health=health,
            top_bottleneck=bottleneck,
            recommended_goal=goal,
            governance=governance,
            next_actions=[goal],
        )
