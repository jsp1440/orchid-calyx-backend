#!/usr/bin/env python3
"""
Orchid Continuum Automation Worker
----------------------------------
Full-file replacement for Replit/Calyx environment.

Key fix:
- Uses PGHOST / PGDATABASE / PGUSER / PGPASSWORD / PGPORT
  instead of DATABASE_URL, because Calyx builds DB connectivity
  from Replit-style Postgres environment variables.

What this worker does:
- Registers itself in oc_worker_registry
- Claims one pending job at a time from oc_job_queue
- Runs approved handlers
- Logs results to oc_job_log
- Marks jobs complete/failed
- Enqueues follow-up jobs
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

WORKER_NAME = os.getenv("OC_WORKER_NAME", "orchid_continuum_worker_01")
POLL_INTERVAL = int(os.getenv("OC_POLL_INTERVAL", "10"))
DEFAULT_TIMEOUT = int(os.getenv("OC_COMMAND_TIMEOUT", "3600"))

# Optional path hints for repos/scripts
SCIENTIFIC_WORKER_REPO = os.getenv("SCIENTIFIC_WORKER_REPO",
                                   "/home/runner/workspace")
MEDIA_WORKER_REPO = os.getenv("MEDIA_WORKER_REPO", "/home/runner/workspace")
CALYX_REPO = os.getenv("CALYX_REPO", "/home/runner/workspace")


def get_conn() -> psycopg2.extensions.connection:
    """
    Replit/Calyx-safe connection method.
    Uses the same PG* environment variables the app already relies on.
    """
    host = os.getenv("PGHOST")
    database = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    port = os.getenv("PGPORT", "5432")

    missing = [
        name for name, value in [
            ("PGHOST", host),
            ("PGDATABASE", database),
            ("PGUSER", user),
            ("PGPASSWORD", password),
        ] if not value
    ]

    if missing:
        raise RuntimeError(
            f"Missing required Postgres environment variables: {', '.join(missing)}"
        )

    return psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=password,
        port=port,
    )


def db_execute(
    sql: str,
    params: Optional[Tuple[Any, ...]] = None,
    fetchone: bool = False,
    fetchall: bool = False,
) -> Any:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()
    return None


def register_worker() -> None:
    sql = """
    INSERT INTO public.oc_worker_registry
        (worker_name, worker_type, status, heartbeat_at, details, created_at, updated_at)
    VALUES
        (%s, %s, 'running', NOW(), %s::jsonb, NOW(), NOW())
    ON CONFLICT (worker_name)
    DO UPDATE SET
        worker_type = EXCLUDED.worker_type,
        status = 'running',
        heartbeat_at = NOW(),
        updated_at = NOW(),
        details = EXCLUDED.details
    """
    details = json.dumps({
        "pid": os.getpid(),
        "python": sys.version,
        "poll_interval": POLL_INTERVAL,
    })
    db_execute(sql, (WORKER_NAME, "automation_worker", details))


def heartbeat_worker(status: str = "running") -> None:
    sql = """
    UPDATE public.oc_worker_registry
    SET status = %s,
        heartbeat_at = NOW(),
        updated_at = NOW()
    WHERE worker_name = %s
    """
    db_execute(sql, (status, WORKER_NAME))


def log_message(
    job_id: int,
    level: str,
    message: str,
    run_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    sql = """
    INSERT INTO public.oc_job_log
        (job_id, run_id, log_level, message, created_at, details)
    VALUES
        (%s, %s, %s, %s, NOW(), %s::jsonb)
    """
    db_execute(
        sql,
        (job_id, run_id, level, message[:20000], json.dumps(details or {})))


def create_job_run(job_id: int) -> int:
    next_run_sql = """
    SELECT COALESCE(MAX(run_number), 0) + 1 AS next_run
    FROM public.oc_job_run
    WHERE job_id = %s
    """
    row = db_execute(next_run_sql, (job_id, ), fetchone=True)
    run_number = int(row["next_run"])

    insert_sql = """
    INSERT INTO public.oc_job_run
        (job_id, run_number, started_at, status, metrics)
    VALUES
        (%s, %s, NOW(), 'running', '{}'::jsonb)
    RETURNING id
    """
    row = db_execute(insert_sql, (job_id, run_number), fetchone=True)
    return int(row["id"])


def finish_job_run(
    run_id: int,
    status: str,
    error_message: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    sql = """
    UPDATE public.oc_job_run
    SET finished_at = NOW(),
        status = %s,
        error_message = %s,
        metrics = %s::jsonb
    WHERE id = %s
    """
    db_execute(sql, (status, error_message, json.dumps(metrics or {}), run_id))


def finish_job(job_id: int, status: str) -> None:
    sql = """
    UPDATE public.oc_job_queue
    SET job_status = %s,
        finished_at = NOW()
    WHERE id = %s
    """
    db_execute(sql, (status, job_id))


def claim_job() -> Optional[Dict[str, Any]]:
    """
    Claim exactly one pending job safely.
    Lower priority number = higher priority.
    """
    sql = """
    WITH candidate AS (
        SELECT id
        FROM public.oc_job_queue
        WHERE job_status = 'pending'
        ORDER BY priority ASC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE public.oc_job_queue q
    SET job_status = 'running',
        started_at = NOW(),
        worker_name = %s
    FROM candidate
    WHERE q.id = candidate.id
    RETURNING
        q.id,
        q.job_type,
        q.payload,
        q.priority,
        q.notes
    """
    return db_execute(sql, (WORKER_NAME, ), fetchone=True)


def enqueue_followups(parent_job_id: int, payload: Dict[str, Any]) -> None:
    followups = payload.get("followup_jobs", [])
    if not isinstance(followups, list) or not followups:
        return

    sql = """
    INSERT INTO public.oc_job_queue
        (job_type, job_status, priority, requested_by, request_source, payload, parent_job_id, notes, created_at)
    VALUES
        (%s, 'pending', %s, 'automation', 'worker_followup', %s::jsonb, %s, %s, NOW())
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in followups:
                job_type = item.get("job_type")
                if not job_type:
                    continue
                priority = int(item.get("priority", 100))
                notes = item.get("notes",
                                 f"Follow-up from job {parent_job_id}")
                child_payload = item.get("payload", {})
                cur.execute(
                    sql,
                    (
                        job_type,
                        priority,
                        json.dumps(child_payload),
                        parent_job_id,
                        notes,
                    ),
                )


def create_artifact(
    job_id: int,
    artifact_type: str,
    artifact_path: Optional[str] = None,
    artifact_table: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    sql = """
    INSERT INTO public.oc_job_artifact
        (job_id, artifact_type, artifact_path, artifact_table, mime_type, created_at, metadata)
    VALUES
        (%s, %s, %s, %s, %s, NOW(), %s::jsonb)
    """
    db_execute(
        sql,
        (
            job_id,
            artifact_type,
            artifact_path,
            artifact_table,
            mime_type,
            json.dumps(metadata or {}),
        ),
    )


def resolve_cwd(cwd_hint: Optional[str]) -> str:
    mapping = {
        "scientific_worker_repo": SCIENTIFIC_WORKER_REPO,
        "media_worker_repo": MEDIA_WORKER_REPO,
        "calyx_repo": CALYX_REPO,
        None: CALYX_REPO,
        "": CALYX_REPO,
    }
    return mapping.get(cwd_hint, cwd_hint or CALYX_REPO)


def run_subprocess(
    command: List[str],
    cwd: str,
    timeout: int,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def handler_python_script(job_id: int, payload: Dict[str, Any],
                          run_id: int) -> None:
    script_path = payload.get("script_path")
    if not script_path:
        raise ValueError(
            "Payload missing script_path for python_script handler")

    cwd = resolve_cwd(payload.get("cwd_hint"))
    timeout = int(payload.get("timeout_seconds", DEFAULT_TIMEOUT))

    log_message(
        job_id,
        "INFO",
        f"Running python script: {script_path}",
        run_id=run_id,
        details={
            "cwd": cwd,
            "timeout": timeout
        },
    )

    result = run_subprocess(["python", script_path], cwd, timeout)

    log_message(
        job_id,
        "INFO",
        "Python script finished",
        run_id=run_id,
        details={
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-12000:],
            "stderr_tail": result.stderr[-12000:],
        },
    )

    for artifact_path in payload.get("artifact_paths", []):
        create_artifact(
            job_id,
            artifact_type="file",
            artifact_path=artifact_path,
            metadata={
                "handler": "python_script",
                "script_path": script_path
            },
        )

    if result.returncode != 0:
        raise RuntimeError(f"python script failed: {script_path}\n"
                           f"stderr:\n{result.stderr[-4000:]}")


def handler_shell_script(job_id: int, payload: Dict[str, Any],
                         run_id: int) -> None:
    script_path = payload.get("script_path")
    if not script_path:
        raise ValueError(
            "Payload missing script_path for shell_script handler")

    cwd = resolve_cwd(payload.get("cwd_hint"))
    timeout = int(payload.get("timeout_seconds", DEFAULT_TIMEOUT))

    log_message(
        job_id,
        "INFO",
        f"Running shell script: {script_path}",
        run_id=run_id,
        details={
            "cwd": cwd,
            "timeout": timeout
        },
    )

    result = run_subprocess(["bash", script_path], cwd, timeout)

    log_message(
        job_id,
        "INFO",
        "Shell script finished",
        run_id=run_id,
        details={
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-12000:],
            "stderr_tail": result.stderr[-12000:],
        },
    )

    for artifact_path in payload.get("artifact_paths", []):
        create_artifact(
            job_id,
            artifact_type="file",
            artifact_path=artifact_path,
            metadata={
                "handler": "shell_script",
                "script_path": script_path
            },
        )

    if result.returncode != 0:
        raise RuntimeError(f"shell script failed: {script_path}\n"
                           f"stderr:\n{result.stderr[-4000:]}")


def handler_shell_sql(job_id: int, payload: Dict[str, Any],
                      run_id: int) -> None:
    """
    Conservative implementation:
    - runs shell wrapper if present
    - logs declared sql path as artifact metadata
    """
    script_path = payload.get("script_path")
    sql_path = payload.get("sql_path")
    if not script_path:
        raise ValueError("Payload missing script_path for shell_sql handler")

    cwd = resolve_cwd(payload.get("cwd_hint"))
    timeout = int(payload.get("timeout_seconds", DEFAULT_TIMEOUT))

    log_message(
        job_id,
        "INFO",
        f"Running shell/sql wrapper: {script_path}",
        run_id=run_id,
        details={
            "cwd": cwd,
            "timeout": timeout,
            "sql_path": sql_path
        },
    )

    result = run_subprocess(["bash", script_path], cwd, timeout)

    log_message(
        job_id,
        "INFO",
        "Shell/sql wrapper finished",
        run_id=run_id,
        details={
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-12000:],
            "stderr_tail": result.stderr[-12000:],
            "sql_path": sql_path,
        },
    )

    for artifact_path in payload.get("artifact_paths", []):
        create_artifact(
            job_id,
            artifact_type="file",
            artifact_path=artifact_path,
            metadata={
                "handler": "shell_sql",
                "script_path": script_path,
                "sql_path": sql_path,
            },
        )

    if sql_path:
        create_artifact(
            job_id,
            artifact_type="sql_reference",
            artifact_path=sql_path,
            mime_type="text/sql",
            metadata={"handler": "shell_sql"},
        )

    if result.returncode != 0:
        raise RuntimeError(f"shell/sql handler failed: {script_path}\n"
                           f"stderr:\n{result.stderr[-4000:]}")


def handler_sql_or_template_build(job_id: int, payload: Dict[str, Any],
                                  run_id: int) -> None:
    log_message(
        job_id,
        "INFO",
        "Placeholder handler reached: sql_or_template_build",
        run_id=run_id,
        details=payload,
    )
    for artifact_path in payload.get("artifact_paths", []):
        create_artifact(
            job_id,
            artifact_type="planned_output",
            artifact_path=artifact_path,
            metadata={"handler": "sql_or_template_build"},
        )


def handler_sql_or_pipeline_build(job_id: int, payload: Dict[str, Any],
                                  run_id: int) -> None:
    log_message(
        job_id,
        "INFO",
        "Placeholder handler reached: sql_or_pipeline_build",
        run_id=run_id,
        details=payload,
    )
    for artifact_path in payload.get("artifact_paths", []):
        create_artifact(
            job_id,
            artifact_type="planned_output",
            artifact_path=artifact_path,
            metadata={"handler": "sql_or_pipeline_build"},
        )


HANDLERS = {
    "python_script": handler_python_script,
    "shell_script": handler_shell_script,
    "shell_sql": handler_shell_sql,
    "sql_or_template_build": handler_sql_or_template_build,
    "sql_or_pipeline_build": handler_sql_or_pipeline_build,
}


def run_job(job: Dict[str, Any]) -> None:
    job_id = int(job["id"])
    job_type = job["job_type"]
    raw_payload = job["payload"] or {}
    payload = json.loads(raw_payload) if isinstance(raw_payload,
                                                    str) else raw_payload

    run_id = create_job_run(job_id)

    log_message(
        job_id,
        "INFO",
        f"Starting job: {job_type}",
        run_id=run_id,
        details={"payload": payload},
    )

    handler_name = payload.get("handler")
    if not handler_name:
        error_message = "Payload missing handler"
        log_message(job_id, "ERROR", error_message, run_id=run_id)
        finish_job_run(run_id, "failed", error_message=error_message)
        finish_job(job_id, "failed")
        return

    handler = HANDLERS.get(handler_name)
    if handler is None:
        error_message = f"Unknown handler: {handler_name}"
        log_message(job_id, "ERROR", error_message, run_id=run_id)
        finish_job_run(run_id, "failed", error_message=error_message)
        finish_job(job_id, "failed")
        return

    try:
        handler(job_id, payload, run_id)
        enqueue_followups(job_id, payload)

        finish_job_run(
            run_id,
            "complete",
            metrics={
                "job_type": job_type,
                "handler": handler_name
            },
        )
        finish_job(job_id, "complete")
        log_message(job_id, "INFO", f"Job complete: {job_type}", run_id=run_id)

    except Exception as exc:
        tb = traceback.format_exc()
        log_message(
            job_id,
            "ERROR",
            f"Job failed: {exc}",
            run_id=run_id,
            details={"traceback": tb[-12000:]},
        )
        finish_job_run(
            run_id,
            "failed",
            error_message=str(exc),
            metrics={"traceback_tail": tb[-4000:]},
        )
        finish_job(job_id, "failed")


def worker_loop() -> None:
    print(f"[{WORKER_NAME}] Orchid Continuum worker starting")
    register_worker()

    while True:
        try:
            heartbeat_worker("running")
            job = claim_job()

            if not job:
                time.sleep(POLL_INTERVAL)
                continue

            run_job(job)

        except KeyboardInterrupt:
            heartbeat_worker("stopped")
            print(f"[{WORKER_NAME}] stopping on keyboard interrupt")
            break

        except Exception as exc:
            print(f"[{WORKER_NAME}] loop error: {exc}", file=sys.stderr)
            try:
                heartbeat_worker("error")
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    worker_loop()
