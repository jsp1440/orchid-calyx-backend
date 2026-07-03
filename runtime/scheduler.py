from __future__ import annotations
from dataclasses import asdict
from .health import HealthMonitorService
from .bottlenecks import BottleneckService
from .goals import GoalPlannerService
from .governance import GovernanceService
from .mission import MissionReporterService
from .memory import RuntimeMemoryWriter


class CalyxHeartbeat:
    """One complete Active Calyx heartbeat cycle.

    Observe -> Diagnose -> Plan -> Govern -> Report -> Remember
    """

    def __init__(self) -> None:
        self.health = HealthMonitorService()
        self.bottlenecks = BottleneckService()
        self.goals = GoalPlannerService()
        self.governance = GovernanceService()
        self.mission = MissionReporterService()
        self.memory = RuntimeMemoryWriter()

    def run_once(self) -> dict:
        health = self.health.run()
        bottleneck = self.bottlenecks.detect(health)
        goal = self.goals.plan(bottleneck)
        governance = self.governance.review_action("write_mission_report", requested_level=3)
        report = self.mission.build_report(health, bottleneck, goal, governance)

        payload = asdict(report)
        self.memory.write_event({"event_type": "calyx_heartbeat", "report": payload})
        return payload


if __name__ == "__main__":
    import json
    print(json.dumps(CalyxHeartbeat().run_once(), indent=2))
