from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from app.mission_control_access import AccessPrincipal, MissionControlRole


FeedProvider = Callable[[], list[dict[str, Any]]]
MetricProvider = Callable[[], dict[str, Any]]


class MissionControlBriefingService:
    """Build role-aware, read-only Mission Control briefing payloads."""

    def __init__(
        self,
        *,
        completeness_provider: FeedProvider,
        harvester_provider: FeedProvider,
        metric_provider: MetricProvider,
    ) -> None:
        self.completeness_provider = completeness_provider
        self.harvester_provider = harvester_provider
        self.metric_provider = metric_provider

    def module_feed(self) -> list[dict[str, Any]]:
        rows = []
        for item in self.completeness_provider():
            rows.append(
                {
                    "module_id": item.get("id"),
                    "name": item.get("display_name") or item.get("name"),
                    "category": item.get("category"),
                    "status": item.get("status") or item.get("health"),
                    "completion": item.get("completion") or item.get("completeness"),
                    "summary": item.get("summary"),
                    "telemetry_source": item.get("telemetry_source"),
                    "blockers": list(item.get("blockers") or []),
                    "recommended_next_action": item.get("recommended_next_action") or item.get("recommendation"),
                    "last_update": item.get("last_update") or item.get("lastChecked"),
                }
            )
        return rows

    def harvester_feed(self) -> list[dict[str, Any]]:
        return [
            {
                "harvester_id": item.get("id") or item.get("harvester_id"),
                "name": item.get("name"),
                "state": item.get("state") or item.get("status"),
                "last_run": item.get("last_run"),
                "heartbeat_at": item.get("heartbeat_at"),
                "errors": list(item.get("errors") or []),
            }
            for item in self.harvester_provider()
        ]

    def briefing_for_principal(self, principal: AccessPrincipal) -> dict[str, Any]:
        modules = self.module_feed()
        harvesters = self.harvester_feed()
        metrics = self.metric_provider()
        role_values = {role.value for role in principal.roles}
        status_counts = Counter(str(item.get("status") or "unknown") for item in modules)
        blockers = [
            {"module_id": item["module_id"], "name": item["name"], "blockers": item["blockers"]}
            for item in modules
            if item["blockers"]
        ]

        payload: dict[str, Any] = {
            "principal_id": principal.principal_id,
            "roles": sorted(role_values),
            "audience": self._audience(role_values),
            "summary": {
                "module_count": len(modules),
                "status_counts": dict(sorted(status_counts.items())),
                "blocker_count": len(blockers),
            },
            "modules": modules,
        }

        if MissionControlRole.VOLUNTEER.value in role_values:
            payload["volunteer_focus"] = [
                item for item in modules if item["status"] in {"warning", "stub"}
            ]

        if MissionControlRole.EXPERT.value in role_values:
            payload["expert_focus"] = blockers
            payload["scientific_metrics"] = metrics

        if MissionControlRole.ADMINISTRATOR.value in role_values:
            payload["operations"] = {
                "harvesters": harvesters,
                "metrics": metrics,
                "blockers": blockers,
            }

        return payload

    @staticmethod
    def _audience(role_values: set[str]) -> str:
        if MissionControlRole.ADMINISTRATOR.value in role_values:
            return "administrator"
        if MissionControlRole.EXPERT.value in role_values:
            return "expert"
        if MissionControlRole.VOLUNTEER.value in role_values:
            return "volunteer"
        return "public"
