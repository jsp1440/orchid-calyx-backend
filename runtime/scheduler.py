from __future__ import annotations

from dataclasses import asdict
import json
import logging
import os
import threading
import time
from typing import Any

from .health import HealthMonitorService
from .bottlenecks import BottleneckService
from .goals import GoalPlannerService
from .governance import GovernanceService
from .infrastructure import InfrastructureRegistryService
from .mission import MissionReporterService
from .memory import RuntimeMemoryWriter

log = logging.getLogger("calyx.scheduler")


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


class InProcessHarvester:
    """Bounded adaptive harvesting inside the existing Calyx web service.

    The thread is intentionally independent of the general autonomous runtime:
    Calyx can continue harvesting on the already-paid web instance even when
    the broader autoloop is disabled. A separate Render worker/cron is not
    required.

    CALYX_INPROCESS_HARVEST_ENABLED can explicitly enable/disable it. When the
    flag is absent, it auto-enables only in a deployed web-service-shaped
    environment (DATABASE_URL + PORT), which keeps imports/tests side-effect
    free by default.
    """

    def __init__(self) -> None:
        explicit = _env_bool("CALYX_INPROCESS_HARVEST_ENABLED")
        auto_deployed = bool(os.environ.get("DATABASE_URL") and os.environ.get("PORT"))
        self.enabled = auto_deployed if explicit is None else explicit
        self.interval_seconds = max(
            300, int(os.environ.get("CALYX_HARVEST_INTERVAL_SECONDS", "900"))
        )
        self.startup_delay_seconds = max(
            5, int(os.environ.get("CALYX_HARVEST_STARTUP_DELAY_SECONDS", "20"))
        )
        self.limit = max(1, int(os.environ.get("CALYX_HARVEST_LIMIT", "10")))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_started_at: float | None = None
        self._last_finished_at: float | None = None

    def start(self) -> bool:
        if not self.enabled:
            log.info("Calyx in-process harvester disabled")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="calyx-inprocess-harvester",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Calyx in-process harvester started interval=%ss limit=%s",
            self.interval_seconds,
            self.limit,
        )
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "interval_seconds": self.interval_seconds,
                "limit": self.limit,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def _loop(self) -> None:
        if self._stop.wait(self.startup_delay_seconds):
            return
        while not self._stop.is_set():
            self._run_cycle()
            if self._stop.wait(self.interval_seconds):
                return

    def _run_cycle(self) -> None:
        with self._lock:
            self._last_started_at = time.time()
            self._last_error = None
        try:
            from adaptive_harvest_worker import run_once

            result = run_once(limit=self.limit)
            with self._lock:
                self._last_result = result
            log.info("Calyx adaptive harvest cycle: %s", json.dumps(result, default=str))
        except Exception as exc:  # harvesting must never take down the API
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            log.exception("Calyx adaptive harvest cycle failed")
        finally:
            with self._lock:
                self._last_finished_at = time.time()


class CalyxHeartbeat:
    """One complete Active Calyx heartbeat cycle.

    Observe -> Diagnose -> Plan -> Govern -> Report -> Remember
    """

    def __init__(self) -> None:
        self.health = HealthMonitorService()
        self.infrastructure = InfrastructureRegistryService()
        self.bottlenecks = BottleneckService()
        self.goals = GoalPlannerService()
        self.governance = GovernanceService()
        self.mission = MissionReporterService()
        self.memory = RuntimeMemoryWriter()
        self.harvester = InProcessHarvester()
        self.harvester.start()

    def run_once(self) -> dict:
        health = self.health.run()
        infrastructure_health = self.infrastructure.health()
        bottleneck = self.bottlenecks.detect(health)
        goal = self.goals.plan(bottleneck)
        governance = self.governance.review_action("write_mission_report", requested_level=3)
        report = self.mission.build_report(health, bottleneck, goal, governance)

        payload = asdict(report)
        payload["brain_config"] = infrastructure_health.get("config_source")
        payload["infrastructure"] = infrastructure_health
        payload["harvester"] = self.harvester.status()
        self.memory.write_event({"event_type": "calyx_heartbeat", "report": payload})
        return payload


if __name__ == "__main__":
    print(json.dumps(CalyxHeartbeat().run_once(), indent=2))
