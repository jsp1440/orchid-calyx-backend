from datetime import datetime, timezone
from typing import Any, Optional
import os

from fastapi import FastAPI
from pydantic import BaseModel

from app.routers import (
    awards,
    calyx_core,
    entries,
    feedback,
    health,
    judging,
    reference_docs,
)
from runtime.autonomous_orchestrator import CalyxAutonomousOrchestrator, OrchestratorConfigError
from runtime.cds_router import router as cds_router
from runtime.planner_router import router as planner_router
from runtime.router_fastapi import router as runtime_router
from runtime.runtime_engine import RuntimeEngine
from runtime.scheduler import CalyxHeartbeat


app = FastAPI()

AUTO_LOOP_ENABLED = os.environ.get("OC_RUNNER_AUTOLOOP", "false").lower() == "true"
AUTO_LOOP_INTERVAL_SECONDS = int(os.environ.get("OC_RUNNER_INTERVAL_SECONDS", "30"))
ACTIVE_MODE = os.environ.get("OC_RUNNER_ACTIVE_MODE", "true").lower() == "true"


class VerificationRequest(BaseModel):
    source_context: Optional[str] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def orchestrator() -> CalyxAutonomousOrchestrator:
    return CalyxAutonomousOrchestrator()


def heartbeat_once() -> dict[str, Any]:
    return CalyxHeartbeat().run_once()


def seed_missions() -> dict[str, Any]:
    result = orchestrator().seed_defaults()
    health_payload = orchestrator().health()
    return {
        **result,
        "queue_depth": health_payload.get("queue_depth"),
        "queue_count": health_payload.get("queue_count"),
    }


def execute_next_runtime_job() -> dict[str, Any]:
    result = orchestrator().run_once()
    health_payload = safe_orchestrator_health()
    return {
        **result,
        "completed": 1 if result.get("status") == "completed" else 0,
        "failed": 1 if result.get("status") == "failed" else 0,
        "queue_depth": health_payload.get("queue_depth"),
    }


def safe_orchestrator_health() -> dict[str, Any]:
    try:
        return orchestrator().health()
    except OrchestratorConfigError as exc:
        return {
            "status": "degraded",
            "error": str(exc),
            "queue_depth": None,
            "queue_count": {},
            "enabled": runtime_engine.status().get("enabled") if "runtime_engine" in globals() else AUTO_LOOP_ENABLED,
        }
    except Exception as exc:  # pragma: no cover - defensive API boundary
        return {
            "status": "failed",
            "error": str(exc),
            "queue_depth": None,
            "queue_count": {},
            "enabled": runtime_engine.status().get("enabled") if "runtime_engine" in globals() else AUTO_LOOP_ENABLED,
        }


runtime_engine = RuntimeEngine(
    heartbeat=heartbeat_once,
    enqueue_jobs=seed_missions,
    execute_jobs=execute_next_runtime_job,
    interval_seconds=AUTO_LOOP_INTERVAL_SECONDS,
    enabled=AUTO_LOOP_ENABLED,
)


@app.get("/")
def read_root():
    return {"status": "Calyx Backend API running"}


@app.post("/verify")
def verify(request: VerificationRequest):
    return {"received": True, "source_context": request.source_context}


@app.get("/api/runner/health")
def runner_health():
    engine = runtime_engine.status()
    queue = safe_orchestrator_health()
    return {
        "status": "runner alive" if queue.get("status") != "failed" else "degraded",
        "autoloop_enabled": AUTO_LOOP_ENABLED,
        "interval_seconds": AUTO_LOOP_INTERVAL_SECONDS,
        "active_mode": ACTIVE_MODE,
        "mode": "build_044_autonomous_runtime_mission_planner",
        **engine,
        "queue_depth": queue.get("queue_depth", engine.get("queue_depth")),
        "queue_count": queue.get("queue_count", {}),
        "orchestrator": queue,
    }


@app.get("/api/runner/summary")
def runner_summary():
    queue = safe_orchestrator_health()
    try:
        agents = orchestrator().list_agents().get("agents", [])
        tasks = orchestrator().list_tasks(limit=40).get("tasks", [])
        runs = orchestrator().runs(limit=20).get("runs", [])
    except Exception as exc:
        agents = []
        tasks = []
        runs = []
        queue = {**queue, "summary_error": str(exc)}

    modules = [
        {
            "module_name": agent.get("agent_name"),
            "capability": agent.get("capability"),
            "priority": agent.get("priority"),
            "enabled": agent.get("enabled"),
            "allowed_task_types": agent.get("allowed_task_types"),
        }
        for agent in agents
    ]
    return {
        "modules": modules,
        "tasks": tasks,
        "runs": runs,
        "runtime_engine": runtime_engine.status(),
        "orchestrator": queue,
    }


@app.get("/api/runner/autonomous-status")
def autonomous_status():
    return {**runtime_engine.status(), "orchestrator": safe_orchestrator_health()}


@app.post("/api/runner/start")
def start_runner():
    persistence: dict[str, Any] | None = None
    try:
        persistence = orchestrator().set_runtime_enabled(True, updated_by="api:start")
    except Exception as exc:
        persistence = {"status": "degraded", "error": str(exc)}
    runtime_engine.set_enabled(True)
    started = runtime_engine.start()
    return {
        "status": "started" if started else "already_running",
        "persistence": persistence,
        "engine": runtime_engine.status(),
    }


@app.post("/api/runner/stop")
def stop_runner():
    stopped = runtime_engine.stop()
    runtime_engine.set_enabled(False)
    persistence: dict[str, Any] | None = None
    try:
        persistence = orchestrator().set_runtime_enabled(False, updated_by="api:stop")
    except Exception as exc:
        persistence = {"status": "degraded", "error": str(exc)}
    return {
        "status": "stopped" if stopped else "still_running",
        "persistence": persistence,
        "engine": runtime_engine.status(),
    }


@app.post("/api/runner/restart")
def restart_runner():
    persistence: dict[str, Any] | None = None
    try:
        persistence = orchestrator().set_runtime_enabled(True, updated_by="api:restart")
    except Exception as exc:
        persistence = {"status": "degraded", "error": str(exc)}
    runtime_engine.set_enabled(True)
    result = runtime_engine.restart()
    return {"status": "restarted" if result.get("started") else "restart_attempted", "persistence": persistence, **result}


@app.post("/api/runner/run-once")
def run_once():
    return runtime_engine.run_cycle()


@app.post("/api/runner/execute-next")
def execute_next():
    return execute_next_runtime_job()


@app.post("/api/runner/execute-all")
def execute_all(limit: int = 25):
    completed = 0
    failed = 0
    results = []
    for _ in range(max(1, min(limit, 100))):
        result = execute_next_runtime_job()
        results.append(result)
        if result.get("status") in {"no_eligible_tasks", "no_jobs"}:
            break
        completed += int(result.get("completed") or 0)
        failed += int(result.get("failed") or 0)
    return {
        "status": "queue_empty" if results and results[-1].get("status") in {"no_eligible_tasks", "no_jobs"} else "stopped",
        "completed": completed,
        "failed": failed,
        "results": results,
    }


@app.post("/api/runner/seed-missions")
def seed_runner_missions():
    return seed_missions()


@app.post("/api/runner/autonomous-cycle")
def autonomous_cycle():
    return runtime_engine.run_cycle()


@app.post("/api/runner/autonomous-start")
def autonomous_start():
    return start_runner()


@app.post("/api/runner/autonomous-stop")
def autonomous_stop():
    return stop_runner()


@app.on_event("startup")
def startup_event():
    if AUTO_LOOP_ENABLED:
        runtime_engine.set_enabled(True)
        runtime_engine.start()


@app.on_event("shutdown")
def shutdown_event():
    runtime_engine.stop()


app.include_router(health.router)
app.include_router(calyx_core.router)
app.include_router(awards.router)
app.include_router(entries.router)
app.include_router(feedback.router)
app.include_router(judging.router)
app.include_router(reference_docs.router)
app.include_router(runtime_router)
app.include_router(cds_router)
app.include_router(planner_router)

from app.routers import orchid_widgets

app.include_router(orchid_widgets.router)
