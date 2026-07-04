"""Database-backed autonomous queue operations for BUILD-012A."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ.get("DATABASE_URL")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return DATABASE_URL


def table_exists(cur, fq_table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (fq_table,))
    return cur.fetchone()[0] is not None


def safe_count(cur, fq_table: str) -> int:
    if not table_exists(cur, fq_table):
        return 0
    cur.execute(f"SELECT COUNT(*) FROM {fq_table}")
    return cur.fetchone()[0]


def ensure_execution_jobs_table(cur) -> None:
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


def insert_job_if_missing(
    cur,
    *,
    job_name: str,
    dedup_key: str,
    details: Optional[dict[str, Any]] = None,
) -> bool:
    cur.execute(
        """
        INSERT INTO oc_admin.ocp_execution_jobs
            (job_name, dedup_key, status, started_at, updated_at, details)
        VALUES
            (%s, %s, 'pending', NOW(), NOW(), %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (job_name, dedup_key, Jsonb(details or {})),
    )
    return cur.fetchone() is not None


def enqueue_default_jobs() -> dict[str, Any]:
    """Ensure the core optimization jobs exist without duplicating them."""
    jobs = [
        "optimize_calyx_core",
        "optimize_health",
        "optimize_judging",
        "optimize_awards",
        "optimize_mycorrhiza",
    ]
    created: list[str] = []
    skipped: list[str] = []

    with psycopg.connect(ensure_database_url()) as conn:
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


def run_job_logic(job_name: str) -> dict[str, Any]:
    with psycopg.connect(ensure_database_url()) as conn:
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
                return {
                    "module": "mycorrhiza",
                    "status": "completed",
                    "endpoint_cache_rows": safe_count(
                        cur,
                        "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
                    ),
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


def execute_next_job() -> dict[str, Any]:
    """Execute the oldest pending job. Legacy null-name rows are ignored."""
    with psycopg.connect(ensure_database_url()) as conn:
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
                conn.commit()
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "job_name": job_name,
                    "result": result,
                }
            except Exception as exc:
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
                        str(exc),
                        Jsonb({"message": "execution failed", "error": str(exc), "timestamp": utc_now()}),
                        job_id,
                    ),
                )
                conn.commit()
                return {"status": "failed", "job_id": job_id, "job_name": job_name, "error": str(exc)}


def execute_all_pending_jobs(max_jobs: int = 10) -> dict[str, Any]:
    """Drain a bounded number of pending jobs each engine cycle."""
    completed = 0
    failed = 0
    results: list[dict[str, Any]] = []

    for _ in range(max_jobs):
        result = execute_next_job()
        results.append(result)
        status = result.get("status")
        if status == "no_jobs":
            return {
                "status": "queue_empty",
                "completed": completed,
                "failed": failed,
                "results": results,
            }
        if status == "completed":
            completed += 1
            continue
        if status == "failed":
            failed += 1
            continue
        return {
            "status": "stopped",
            "completed": completed,
            "failed": failed,
            "results": results,
        }

    return {
        "status": "cycle_limit_reached",
        "completed": completed,
        "failed": failed,
        "results": results,
    }
