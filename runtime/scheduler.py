from __future__ import annotations

from dataclasses import asdict
import json
import logging
import os
import socket
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
    """Bounded adaptive harvesting inside the existing Calyx web service."""

    def __init__(self) -> None:
        explicit = _env_bool("CALYX_INPROCESS_HARVEST_ENABLED")
        auto_deployed = bool(os.environ.get("DATABASE_URL") and os.environ.get("PORT"))
        self.enabled = auto_deployed if explicit is None else explicit
        self.interval_seconds = max(300, int(os.environ.get("CALYX_HARVEST_INTERVAL_SECONDS", "900")))
        self.startup_delay_seconds = max(5, int(os.environ.get("CALYX_HARVEST_STARTUP_DELAY_SECONDS", "20")))
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
        self._thread = threading.Thread(target=self._loop, name="calyx-inprocess-harvester", daemon=True)
        self._thread.start()
        log.info("Calyx in-process harvester started interval=%ss limit=%s", self.interval_seconds, self.limit)
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"enabled": self.enabled, "thread_alive": bool(self._thread and self._thread.is_alive()), "interval_seconds": self.interval_seconds, "limit": self.limit, "last_started_at": self._last_started_at, "last_finished_at": self._last_finished_at, "last_result": self._last_result, "last_error": self._last_error}

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
        except Exception as exc:
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            log.exception("Calyx adaptive harvest cycle failed")
        finally:
            with self._lock:
                self._last_finished_at = time.time()


class InProcessEngineeringCompletion:
    """Poll governed engineering jobs inside the existing paid web service."""

    def __init__(self) -> None:
        self.explicit = _env_bool("CALYX_INPROCESS_ENGINEERING_ENABLED")
        self.interval_seconds = max(5, int(os.environ.get("CALYX_ENGINEERING_POLL_SECONDS", "30")))
        self.startup_delay_seconds = max(5, int(os.environ.get("CALYX_ENGINEERING_STARTUP_DELAY_SECONDS", "10")))
        self.lease_seconds = max(60, int(os.environ.get("CALYX_ORCHESTRATOR_LEASE_SECONDS", "300")))
        self.worker_id = os.environ.get("CALYX_WORKER_ID", f"web-{socket.gethostname()}-{os.getpid()}")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_result: str | None = None
        self._last_error: str | None = None
        self._last_started_at: float | None = None
        self._last_finished_at: float | None = None

    def runtime_ready(self) -> bool:
        if self.explicit is False:
            return False
        try:
            from app.calyx_orchestrator.worker import engineering_runtime_ready
            ready = engineering_runtime_ready()
        except Exception:
            return False
        return ready if self.explicit is None else bool(self.explicit and ready)

    def start(self) -> bool:
        if not self.runtime_ready():
            log.info("Calyx in-process engineering completion disabled/not ready")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="calyx-inprocess-engineering", daemon=True)
        self._thread.start()
        log.info("Calyx in-process engineering completion started interval=%ss", self.interval_seconds)
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"runtime_ready": self.runtime_ready(), "thread_alive": bool(self._thread and self._thread.is_alive()), "interval_seconds": self.interval_seconds, "last_started_at": self._last_started_at, "last_finished_at": self._last_finished_at, "last_result": self._last_result, "last_error": self._last_error}

    def _loop(self) -> None:
        if self._stop.wait(self.startup_delay_seconds):
            return
        from app.database import get_session_local
        from app.calyx_orchestrator.worker import run_cycle
        SessionLocal = get_session_local()
        while not self._stop.is_set():
            with self._lock:
                self._last_started_at = time.time()
                self._last_error = None
            db = SessionLocal()
            try:
                result = run_cycle(db, worker_id=self.worker_id, lease_seconds=self.lease_seconds)
                with self._lock:
                    self._last_result = result
                if result != "idle":
                    log.info("Calyx in-process engineering cycle: %s", result)
            except Exception as exc:
                db.rollback()
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Calyx in-process engineering cycle failed")
            finally:
                db.close()
                with self._lock:
                    self._last_finished_at = time.time()
            if self._stop.wait(self.interval_seconds):
                return


class CalyxHeartbeat:
    """One complete Active Calyx heartbeat cycle."""

    def __init__(self) -> None:
        self.health = HealthMonitorService()
        self.infrastructure = InfrastructureRegistryService()
        self.bottlenecks = BottleneckService()
        self.goals = GoalPlannerService()
        self.governance = GovernanceService()
        self.mission = MissionReporterService()
        self.memory = RuntimeMemoryWriter()
        self.harvester = InProcessHarvester()
        self.engineering = InProcessEngineeringCompletion()
        self.harvester.start()
        self.engineering.start()

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
        payload["engineering_completion"] = self.engineering.status()
        self.memory.write_event({"event_type": "calyx_heartbeat", "report": payload})
        return payload


if __name__ == "__main__":
    print(json.dumps(CalyxHeartbeat().run_once(), indent=2))
