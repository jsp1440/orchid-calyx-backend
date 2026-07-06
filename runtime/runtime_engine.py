"""Autonomous runtime engine for Calyx.

BUILD-012A turns the existing request/response runner into a small
background service that can keep Calyx alive without requiring a human to
press `/api/runner/execute-next`.

The engine is intentionally dependency-injected: FastAPI owns the concrete
runner functions, while this module owns lifecycle, timing, status, and
single-instance safety. That keeps this file reusable and avoids importing
`app.main` back into the runtime package.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


RuntimeCallable = Callable[[], Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RuntimeEngineState:
    """Serializable runtime engine state for API/dashboard use."""

    enabled: bool
    running: bool = False
    interval_seconds: int = 30
    cycle_count: int = 0
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    last_cycle_started_at: Optional[str] = None
    last_cycle_finished_at: Optional[str] = None
    last_heartbeat_status: Optional[str] = None
    last_enqueue_status: Optional[str] = None
    last_execute_status: Optional[str] = None
    last_execute_completed: Optional[int] = None
    last_execute_failed: Optional[int] = None
    last_error: Optional[str] = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "interval_seconds": self.interval_seconds,
            "cycle_count": self.cycle_count,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_cycle_started_at": self.last_cycle_started_at,
            "last_cycle_finished_at": self.last_cycle_finished_at,
            "last_heartbeat_status": self.last_heartbeat_status,
            "last_enqueue_status": self.last_enqueue_status,
            "last_execute_status": self.last_execute_status,
            "last_execute_completed": self.last_execute_completed,
            "last_execute_failed": self.last_execute_failed,
            "last_error": self.last_error,
            "events": self.events[-20:],
        }


class RuntimeEngine:
    """Background loop that runs heartbeat + queue execution.

    The engine is deliberately conservative:
    - start() is idempotent
    - stop() is graceful
    - every cycle catches and records errors
    - only one thread is created per process
    """

    def __init__(
        self,
        *,
        heartbeat: RuntimeCallable,
        enqueue_jobs: RuntimeCallable,
        execute_jobs: RuntimeCallable,
        interval_seconds: int = 30,
        enabled: bool = True,
    ) -> None:
        self.heartbeat = heartbeat
        self.enqueue_jobs = enqueue_jobs
        self.execute_jobs = execute_jobs
        self.state = RuntimeEngineState(
            enabled=enabled,
            interval_seconds=max(5, int(interval_seconds)),
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def set_enabled(self, enabled: bool) -> None:
        """Transition the runtime enabled flag without starting or stopping it."""
        with self._lock:
            self.state.enabled = enabled
            self._record_event("runtime_enabled" if enabled else "runtime_disabled")

    def start(self) -> bool:
        """Start the runtime loop if enabled and not already running."""
        if not self.state.enabled:
            self._record_event("runtime_engine_disabled")
            return False

        with self._lock:
            if self._thread and self._thread.is_alive():
                self.state.running = True
                self._record_event("runtime_engine_already_running")
                return False

            self._stop_event.clear()
            self.state.running = True
            self.state.started_at = utc_now()
            self.state.stopped_at = None
            self._thread = threading.Thread(
                target=self._run_loop,
                name="calyx-runtime-engine",
                daemon=True,
            )
            self._thread.start()
            self._record_event("runtime_engine_started")
            return True

    def stop(self, timeout_seconds: float = 5.0) -> bool:
        """Request graceful shutdown."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout_seconds)

        with self._lock:
            self.state.running = bool(thread and thread.is_alive())
            if not self.state.running:
                self.state.stopped_at = utc_now()
                self._record_event("runtime_engine_stopped")
            return not self.state.running

    def run_cycle(self) -> dict[str, Any]:
        """Run exactly one autonomous cycle.

        This is useful both for the background thread and for deterministic
        testing/API inspection.
        """
        started = utc_now()
        with self._lock:
            self.state.last_cycle_started_at = started
            self.state.last_error = None

        heartbeat_result: Any = None
        enqueue_result: Any = None
        execute_result: Any = None

        try:
            heartbeat_result = self.heartbeat()
            enqueue_result = self.enqueue_jobs()
            execute_result = self.execute_jobs()

            with self._lock:
                self.state.cycle_count += 1
                self.state.last_cycle_finished_at = utc_now()
                self.state.last_heartbeat_status = self._status_from(heartbeat_result)
                self.state.last_enqueue_status = self._status_from(enqueue_result)
                self.state.last_execute_status = self._status_from(execute_result)
                if isinstance(execute_result, dict):
                    self.state.last_execute_completed = execute_result.get("completed")
                    self.state.last_execute_failed = execute_result.get("failed")
                self._record_event(
                    "runtime_cycle_completed",
                    {
                        "heartbeat_status": self.state.last_heartbeat_status,
                        "enqueue_status": self.state.last_enqueue_status,
                        "execute_status": self.state.last_execute_status,
                        "completed": self.state.last_execute_completed,
                        "failed": self.state.last_execute_failed,
                    },
                )

            return {
                "status": "completed",
                "started_at": started,
                "finished_at": self.state.last_cycle_finished_at,
                "heartbeat": heartbeat_result,
                "enqueue": enqueue_result,
                "execute": execute_result,
            }
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            with self._lock:
                self.state.cycle_count += 1
                self.state.last_cycle_finished_at = utc_now()
                self.state.last_error = str(exc)
                self._record_event("runtime_cycle_failed", {"error": str(exc)})
            return {
                "status": "failed",
                "started_at": started,
                "finished_at": self.state.last_cycle_finished_at,
                "error": str(exc),
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self.state.to_dict()
        state["thread_alive"] = bool(self._thread and self._thread.is_alive())
        return state

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_cycle()
            self._stop_event.wait(self.state.interval_seconds)

        with self._lock:
            self.state.running = False
            self.state.stopped_at = utc_now()

    def _status_from(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("status") or value.get("overall_status") or "ok")
        return "ok"

    def _record_event(self, name: str, details: Optional[dict[str, Any]] = None) -> None:
        self.state.events.append(
            {
                "event": name,
                "timestamp": utc_now(),
                "details": details or {},
            }
        )
        if len(self.state.events) > 100:
            self.state.events = self.state.events[-100:]
