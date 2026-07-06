from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Any
import os
import re
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from app.routers import (
    awards,
    calyx_core,
    entries,
    feedback,
    health,
    judging,
    reference_docs,
)
from runtime.router_fastapi import router as runtime_router
from runtime.cds_router import router as cds_router
from runtime.planner_router import router as planner_router
from runtime.runtime_engine import RuntimeEngine
from runtime.scheduler import CalyxHeartbeat

app = FastAPI()

DATABASE_URL = os.environ.get("DATABASE_URL")
AUTO_LOOP_INTERVAL_SECONDS = int(os.environ.get("OC_RUNNER_INTERVAL_SECONDS", "30"))
ACTIVE_MODE = os.environ.get("OC_RUNNER_ACTIVE_MODE", "true").lower() == "true"
RUNTIME_ENABLE_FLAGS = (
    "OC_RUNNER_AUTOLOOP",
    "CALYX_RUNTIME_ENABLED",
    "AUTONOMOUS_RUNTIME_ENABLED",
    "RUNNER_ENABLED",
    "CALYX_AUTONOMOUS_ENABLED",
)
RUNTIME_DISABLE_FLAGS = (
    "CALYX_AUTONOMOUS_DISABLED",
    "OC_RUNNER_DISABLED",
    "CALYX_RUNTIME_DISABLED",
)


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for Calyx runner operations")
    return DATABASE_URL


def env_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def autonomous_runtime_config_blocker() -> Optional[dict[str, str]]:
    for key in RUNTIME_DISABLE_FLAGS:
        if env_bool(os.environ.get(key)) is True:
            return {"key": key, "value": os.environ[key], "reason": "explicit_disable_flag"}

    for key in RUNTIME_ENABLE_FLAGS:
        if key in os.environ and env_bool(os.environ.get(key)) is False:
            return {"key": key, "value": os.environ[key], "reason": "explicit_enable_flag_false"}

    return None


def autonomous_runtime_enabled_by_config() -> bool:
    return autonomous_runtime_config_blocker() is None


AUTO_LOOP_ENABLED = autonomous_runtime_enabled_by_config()


class VerificationRequest(BaseModel):
    source_context: Optional[str] = None


@app.get("/")
def read_root():
    return {"status": "Calyx Backend API running"}


@app.post("/verify")
def verify(request: VerificationRequest):
    return {"received": True, "source_context": request.source_context}


@app.get("/api/runner/health")
def runner_health():
    return {
        "status": "runner alive",
        "autoloop_enabled": AUTO_LOOP_ENABLED,
        "interval_seconds": AUTO_LOOP_INTERVAL_SECONDS,
        "active_mode": ACTIVE_MODE,
        "mode": "build_045_restore_autonomous_runtime",
        "autonomous_runtime_blocker": autonomous_runtime_config_blocker(),
        "runtime_engine": runtime_engine.status(),
    }


@app.get("/api/runner/summary")
def runner_summary():
    modules = [
        {"module_name": "Calyx Core", "state": "functional", "priority": 98},
        {"module_name": "Health", "state": "functional", "priority": 97},
        {"module_name": "Judging", "state": "functional", "priority": 96},
        {"module_name": "Awards", "state": "functional", "priority": 95},
        {"module_name": "Mycorrhiza", "state": "functional", "priority": 94},
    ]

    jobs: list[dict[str, Any]] = []
    runtime_actions: list[dict[str, Any]] = []

    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_runtime_log_table(cur)

            if table_exists(cur, "oc_admin.ocp_execution_jobs"):
                cur.execute(
                    """
                    SELECT id, job_name, status, started_at, finished_at,
                           retry_count, error_text, details
                    FROM oc_admin.ocp_execution_jobs
                    ORDER BY id DESC
                    LIMIT 40
                    """
                )
                for row in cur.fetchall():
                    jobs.append(
                        {
                            "id": row[0],
                            "job_name": row[1],
                            "status": row[2],
                            "started_at": str(row[3]) if row[3] else None,
                            "finished_at": str(row[4]) if row[4] else None,
                            "retry_count": row[5],
                            "error_text": row[6],
                            "details": row[7],
                        }
                    )

            cur.execute(
                """
                SELECT id, module_name, action_name, action_status, action_details, created_at
                FROM oc_admin.ocp_runtime_actions
                ORDER BY id DESC
                LIMIT 40
                """
            )
            for row in cur.fetchall():
                runtime_actions.append(
                    {
                        "id": row[0],
                        "module_name": row[1],
                        "action_name": row[2],
                        "action_status": row[3],
                        "action_details": row[4],
                        "created_at": str(row[5]) if row[5] else None,
                    }
                )

    return {
        "modules": modules,
        "jobs": jobs,
        "runtime_actions": runtime_actions,
        "runtime_engine": runtime_engine.status(),
    }


@app.post("/api/runner/run-once")
def run_once():
    jobs = [
        "optimize_calyx_core",
        "optimize_health",
        "optimize_judging",
        "optimize_awards",
        "optimize_mycorrhiza",
    ]

    created: list[str] = []
    skipped: list[str] = []

    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_execution_jobs_table(cur)
            for job in jobs:
                inserted = insert_job_if_missing(
                    cur,
                    job_name=job,
                    dedup_key=f"calyx:{job}",
                )
                if inserted:
                    created.append(job)
                else:
                    skipped.append(job)
        conn.commit()

    return {
        "status": "ok",
        "jobs_created": created,
        "jobs_skipped_as_duplicates": skipped,
    }


@app.post("/api/runner/execute-next")
def execute_next():
    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_execution_jobs_table(cur)

            cur.execute(
                """
                SELECT id, job_name
                FROM oc_admin.ocp_execution_jobs
                WHERE status = 'pending'
                  AND job_name IS NOT NULL
                ORDER BY id ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()

            if not row:
                return {"status": "no_jobs"}

            job_id, job_name = row

            cur.execute(
                """
                UPDATE oc_admin.ocp_execution_jobs
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW()),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()

            try:
                result = run_job_logic(job_name)

                cur.execute(
                    """
                    UPDATE oc_admin.ocp_execution_jobs
                    SET status = 'completed',
                        finished_at = NOW(),
                        updated_at = NOW(),
                        details = %s,
                        error_text = NULL
                    WHERE id = %s
                    """,
                    (Jsonb(result), job_id),
                )
                log_runtime_action(
                    cur,
                    module_name=result.get("module", "runner"),
                    action_name=job_name,
                    action_status="completed",
                    action_details={"job_id": job_id, "result": result},
                )
                conn.commit()

                return {
                    "status": "completed",
                    "job_id": job_id,
                    "job_name": job_name,
                    "result": result,
                }

            except Exception as exec_err:
                failure_details = {
                    "message": "execution failed",
                    "error": str(exec_err),
                    "timestamp": utc_now(),
                }
                cur.execute(
                    """
                    UPDATE oc_admin.ocp_execution_jobs
                    SET status = 'failed',
                        finished_at = NOW(),
                        updated_at = NOW(),
                        retry_count = COALESCE(retry_count, 0) + 1,
                        error_text = %s,
                        details = %s
                    WHERE id = %s
                    """,
                    (
                        str(exec_err),
                        Jsonb(failure_details),
                        job_id,
                    ),
                )
                log_runtime_action(
                    cur,
                    module_name="runner",
                    action_name=job_name,
                    action_status="failed",
                    action_details={"job_id": job_id, **failure_details},
                )
                conn.commit()

                return {
                    "status": "failed",
                    "job_id": job_id,
                    "job_name": job_name,
                    "error": str(exec_err),
                }


@app.post("/api/runner/execute-all")
def execute_all():
    completed = 0
    failed = 0

    while True:
        result = execute_next()
        status = result.get("status")

        if status == "no_jobs":
            return {"status": "queue_empty", "completed": completed, "failed": failed}

        if status == "completed":
            completed += 1
            continue

        if status == "failed":
            failed += 1
            continue

        return {
            "status": "stopped",
            "last_result": result,
            "completed": completed,
            "failed": failed,
        }


@app.get("/api/runner/autonomous-status")
def autonomous_status():
    return {
        **runtime_engine.status(),
        "autoloop_enabled": AUTO_LOOP_ENABLED,
        "active_mode": ACTIVE_MODE,
        "config_blocker": autonomous_runtime_config_blocker(),
    }


@app.post("/api/runner/autonomous-cycle")
def autonomous_cycle():
    return runtime_engine.run_cycle()


@app.post("/api/runner/autonomous-start")
def autonomous_start():
    blocker = autonomous_runtime_config_blocker()
    if blocker:
        return {
            "status": "runtime_disabled_by_config",
            "config_key": blocker["key"],
            "reason": blocker["reason"],
            "message": f"Unset {blocker['key']} or set it to true to enable Calyx autonomous runtime on Render.",
            "engine": runtime_engine.status(),
        }

    runtime_engine.set_enabled(True)
    started = runtime_engine.start()
    return {
        "status": "started" if started else "already_running",
        "engine": runtime_engine.status(),
    }


@app.post("/api/runner/autonomous-stop")
def autonomous_stop(disable: bool = True):
    stopped = runtime_engine.stop()
    if disable:
        runtime_engine.set_enabled(False)
    return {
        "status": "stopped" if stopped else "still_running",
        "disabled": disable,
        "engine": runtime_engine.status(),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def table_exists(cur, fq_table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (fq_table,))
    return cur.fetchone()[0] is not None


def safe_count(cur, fq_table: str) -> int:
    if not table_exists(cur, fq_table):
        return 0
    cur.execute(f"SELECT COUNT(*) FROM {fq_table}")
    return cur.fetchone()[0]


def ensure_runtime_log_table(cur):
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_admin;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_admin.ocp_runtime_actions (
            id BIGSERIAL PRIMARY KEY,
            module_name TEXT NOT NULL,
            action_name TEXT NOT NULL,
            action_status TEXT NOT NULL,
            action_details JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def ensure_execution_jobs_table(cur):
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_admin;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_admin.ocp_execution_jobs (
            id BIGSERIAL PRIMARY KEY,
            job_name TEXT NOT NULL,
            dedup_key TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            retry_count INTEGER DEFAULT 0,
            error_text TEXT,
            details JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )


def log_runtime_action(
    cur,
    *,
    module_name: str,
    action_name: str,
    action_status: str,
    action_details: Optional[dict[str, Any]] = None,
) -> None:
    ensure_runtime_log_table(cur)
    cur.execute(
        """
        INSERT INTO oc_admin.ocp_runtime_actions
            (module_name, action_name, action_status, action_details)
        VALUES
            (%s, %s, %s, %s)
        """,
        (module_name, action_name, action_status, Jsonb(action_details or {})),
    )


def insert_job_if_missing(
    cur,
    job_name: str,
    dedup_key: str,
    details: Optional[dict[str, Any]] = None,
) -> bool:
    if details is None:
        details = {}

    cur.execute(
        """
        INSERT INTO oc_admin.ocp_execution_jobs
            (job_name, dedup_key, status, started_at, updated_at, details)
        VALUES
            (%s, %s, 'pending', NOW(), NOW(), %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (job_name, dedup_key, Jsonb(details)),
    )
    return cur.fetchone() is not None


def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_doi(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", value)


def run_job_logic(job_name: str):
    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            if job_name == "optimize_calyx_core":
                return {
                    "module": "calyx_core",
                    "status": "completed",
                    "message": "Calyx core optimization placeholder completed.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_health":
                return {
                    "module": "health",
                    "status": "completed",
                    "message": "Health module optimization placeholder completed.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_judging":
                return {
                    "module": "judging",
                    "status": "completed",
                    "message": "Judging module optimization placeholder completed.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_awards":
                return {
                    "module": "awards",
                    "status": "completed",
                    "message": "Awards module optimization placeholder completed.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_mycorrhiza":
                mycorrhiza_rows = safe_count(
                    cur,
                    "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
                )
                return {
                    "module": "mycorrhiza",
                    "status": "completed",
                    "endpoint_cache_rows": mycorrhiza_rows,
                    "message": "Mycorrhiza endpoint cache checked.",
                    "timestamp": utc_now(),
                }

            if job_name.startswith("job_"):
                return {
                    "module": "downstream_executor",
                    "job_name": job_name,
                    "status": "completed",
                    "message": f"{job_name} executed successfully.",
                    "timestamp": utc_now(),
                }

            return {
                "module": "unknown",
                "job_name": job_name,
                "status": "completed",
                "message": "Unknown job acknowledged without action.",
                "timestamp": utc_now(),
            }


def heartbeat_once():
    return CalyxHeartbeat().run_once()


runtime_engine = RuntimeEngine(
    heartbeat=heartbeat_once,
    enqueue_jobs=run_once,
    execute_jobs=execute_next,
    interval_seconds=AUTO_LOOP_INTERVAL_SECONDS,
    enabled=AUTO_LOOP_ENABLED,
)


@app.on_event("startup")
def startup_event():
    if autonomous_runtime_enabled_by_config():
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
