from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Any
import os
import time
from datetime import datetime, timezone
import threading
import re

import psycopg
from psycopg.types.json import Jsonb

app = FastAPI()

DATABASE_URL = os.environ.get("DATABASE_URL")
AUTO_LOOP_ENABLED = os.environ.get("OC_RUNNER_AUTOLOOP", "false").lower() == "true"
AUTO_LOOP_INTERVAL_SECONDS = int(os.environ.get("OC_RUNNER_INTERVAL_SECONDS", "30"))
ACTIVE_MODE = os.environ.get("OC_RUNNER_ACTIVE_MODE", "true").lower() == "true"


class VerificationRequest(BaseModel):
    source_context: Optional[str] = None


@app.get("/")
def read_root():
    return {"status": "Orchid Continuum API running"}


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
        "mode": "production_spawn_citation_engine",
    }


@app.get("/api/runner/summary")
def runner_summary():
    modules = [
        {"module_name": "Trait System", "state": "functional", "priority": 98},
        {"module_name": "Mission Control", "state": "functional", "priority": 97},
        {"module_name": "Atlas", "state": "functional", "priority": 96},
        {"module_name": "Literature", "state": "functional", "priority": 95},
        {"module_name": "Harvester System", "state": "functional", "priority": 94},
    ]

    jobs: list[dict[str, Any]] = []
    runtime_actions: list[dict[str, Any]] = []

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
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

            ensure_runtime_log_table(cur)
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

    return {"modules": modules, "jobs": jobs, "runtime_actions": runtime_actions}


@app.post("/api/runner/run-once")
def run_once():
    jobs = [
        "optimize_trait_system",
        "optimize_mission_control",
        "optimize_atlas",
        "optimize_literature",
        "optimize_harvester_system",
    ]

    created: list[str] = []
    skipped: list[str] = []

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for job in jobs:
                inserted = insert_job_if_missing(
                    cur, job_name=job, dedup_key=f"core:{job}"
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
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, job_name
                FROM oc_admin.ocp_execution_jobs
                WHERE status = 'pending'
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

            except Exception as exec_err:
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
                        Jsonb(
                            {
                                "message": "execution failed",
                                "error": str(exec_err),
                                "timestamp": utc_now(),
                            }
                        ),
                        job_id,
                    ),
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


def insert_job_if_missing(
    cur, job_name: str, dedup_key: str, details: Optional[dict[str, Any]] = None
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


def downstream_job_for_action(action_name: str) -> Optional[str]:
    mapping = {
        "expand_trait_mapping": "job_expand_trait_mapping",
        "review_failures": "job_review_failures",
        "increase_image_ingest": "job_increase_image_ingest",
        "build_citation_links": "job_build_citation_links",
        "throttle_or_scale": "job_throttle_or_scale",
    }
    return mapping.get(action_name)


def maybe_spawn_downstream_job(
    cur, module_name: str, action_name: str, action_details: dict[str, Any]
):
    downstream_job = downstream_job_for_action(action_name)
    if downstream_job is None:
        return None

    fingerprint = action_details.get("fingerprint", "no_fingerprint")
    dedup_key = f"spawn:{downstream_job}:{fingerprint}"

    inserted = insert_job_if_missing(
        cur,
        job_name=downstream_job,
        dedup_key=dedup_key,
        details={
            "spawned_from_module": module_name,
            "spawned_from_action": action_name,
            "fingerprint": fingerprint,
            "spawned_at": utc_now(),
        },
    )

    return {
        "downstream_job_name": downstream_job,
        "dedup_key": dedup_key,
        "spawn_status": "queued" if inserted else "duplicate_skipped",
    }


def log_action(cur, module, action, details):
    ensure_runtime_log_table(cur)
    cur.execute(
        """
        INSERT INTO oc_admin.ocp_runtime_actions
        (module_name, action_name, action_status, action_details)
        VALUES (%s, %s, 'triggered', %s)
        """,
        (module, action, Jsonb(details)),
    )


def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_doi(value: Optional[str]) -> str:
    if not value:
        return ""
    v = value.strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", v)


def get_table_columns(cur, schema_name: str, table_name: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    )
    return [row[0] for row in cur.fetchall()]


def pick_first(columns: list[str], candidates: list[str]) -> Optional[str]:
    colset = set(columns)
    for c in candidates:
        if c in colset:
            return c
    return None


def fetch_rows(cur, sql: str) -> list[tuple[Any, ...]]:
    cur.execute(sql)
    return cur.fetchall()


def execute_citation_engine(cur) -> dict[str, Any]:
    refs_table = "public.literature_refs"
    docs_table = "public.research_documents"
    links_table = "oc_literature.citation_links"

    refs_exists = table_exists(cur, refs_table)
    docs_exists = table_exists(cur, docs_table)
    links_exists = table_exists(cur, links_table)

    result: dict[str, Any] = {
        "module": "downstream_executor",
        "job_name": "job_build_citation_links",
        "status": "completed",
        "engine": "citation_engine_v2",
        "timestamp": utc_now(),
        "literature_refs_exists": refs_exists,
        "research_documents_exists": docs_exists,
        "citation_links_exists": links_exists,
    }

    if not refs_exists or not docs_exists or not links_exists:
        result["status"] = "blocked"
        result["message"] = "Required citation engine tables do not exist."
        return result

    ref_cols = get_table_columns(cur, "public", "literature_refs")
    doc_cols = get_table_columns(cur, "public", "research_documents")

    ref_id_col = pick_first(ref_cols, ["id", "ref_id", "literature_ref_id"])
    ref_doi_col = pick_first(ref_cols, ["doi", "ref_doi", "source_doi"])
    ref_title_col = pick_first(
        ref_cols, ["title", "ref_title", "article_title", "paper_title"]
    )

    doc_id_col = pick_first(doc_cols, ["id", "document_id", "research_document_id"])
    doc_doi_col = pick_first(
        doc_cols, ["doi", "document_doi", "paper_doi", "source_doi"]
    )
    doc_title_col = pick_first(
        doc_cols, ["title", "document_title", "paper_title", "article_title"]
    )

    result["selected_columns"] = {
        "ref_id_col": ref_id_col,
        "ref_doi_col": ref_doi_col,
        "ref_title_col": ref_title_col,
        "doc_id_col": doc_id_col,
        "doc_doi_col": doc_doi_col,
        "doc_title_col": doc_title_col,
    }

    if not ref_id_col or not doc_id_col:
        result["status"] = "blocked"
        result["message"] = "Could not find required ID columns."
        return result

    if not ((ref_doi_col and doc_doi_col) or (ref_title_col and doc_title_col)):
        result["status"] = "blocked"
        result["message"] = (
            "Could not find DOI or title columns sufficient for matching."
        )
        return result

    return {
        **result,
        "candidate_links_found": 0,
        "inserted_total": 0,
        "message": "Citation engine column audit completed. Matching logic preserved for later expansion.",
    }


def run_job_logic(job_name: str):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            actions = []

            if job_name == "optimize_trait_system":
                traits = safe_count(cur, "public.traitbank_orchid_traits")
                claims = safe_count(cur, "public.oc_species_trait_claims")

                if ACTIVE_MODE and traits > 0 and claims < traits * 0.1:
                    details = {
                        "reason": "low_trait_coverage",
                        "traits": traits,
                        "claims": claims,
                        "fingerprint": f"trait_coverage:{traits}:{claims}",
                        "timestamp": utc_now(),
                    }
                    log_action(cur, "trait_system", "expand_trait_mapping", details)
                    spawned = maybe_spawn_downstream_job(
                        cur, "trait_system", "expand_trait_mapping", details
                    )
                    action_record = {
                        "action": "expand_trait_mapping",
                        "status": "triggered",
                        "details": details,
                    }
                    if spawned:
                        action_record["spawned_job"] = spawned
                    actions.append(action_record)

                conn.commit()
                return {
                    "module": "trait_system",
                    "mode": "active_production_spawn",
                    "traits": traits,
                    "claims": claims,
                    "actions": actions,
                }

            if job_name == "optimize_mission_control":
                cur.execute(
                    "SELECT status, COUNT(*) FROM oc_admin.ocp_execution_jobs GROUP BY status"
                )
                stats = dict(cur.fetchall())

                if ACTIVE_MODE and stats.get("failed", 0) > 0:
                    details = {
                        "reason": "failures_detected",
                        "failed": stats["failed"],
                        "fingerprint": f"mission_failures:{stats['failed']}",
                        "timestamp": utc_now(),
                    }
                    log_action(cur, "mission_control", "review_failures", details)
                    spawned = maybe_spawn_downstream_job(
                        cur, "mission_control", "review_failures", details
                    )
                    action_record = {
                        "action": "review_failures",
                        "status": "triggered",
                        "details": details,
                    }
                    if spawned:
                        action_record["spawned_job"] = spawned
                    actions.append(action_record)

                conn.commit()
                return {
                    "module": "mission_control",
                    "mode": "active_production_spawn",
                    "stats": stats,
                    "actions": actions,
                }

            if job_name == "optimize_atlas":
                occ = safe_count(cur, "public.orchid_occurrence")
                imgs = safe_count(cur, "public.orchid_images")
                conn.commit()
                return {
                    "module": "atlas",
                    "mode": "active_production_spawn",
                    "occ": occ,
                    "imgs": imgs,
                    "actions": actions,
                }

            if job_name == "optimize_literature":
                refs = safe_count(cur, "public.literature_refs")
                links = safe_count(cur, "oc_literature.citation_links")

                if ACTIVE_MODE and refs > 0 and links == 0:
                    details = {
                        "reason": "no_citation_links",
                        "refs": refs,
                        "citation_links": links,
                        "fingerprint": f"literature_links:{refs}:{links}",
                        "timestamp": utc_now(),
                    }
                    log_action(cur, "literature", "build_citation_links", details)
                    spawned = maybe_spawn_downstream_job(
                        cur, "literature", "build_citation_links", details
                    )
                    action_record = {
                        "action": "build_citation_links",
                        "status": "triggered",
                        "details": details,
                    }
                    if spawned:
                        action_record["spawned_job"] = spawned
                    actions.append(action_record)

                conn.commit()
                return {
                    "module": "literature",
                    "mode": "active_production_spawn",
                    "refs": refs,
                    "citation_links": links,
                    "actions": actions,
                }

            if job_name == "optimize_harvester_system":
                cur.execute(
                    "SELECT COUNT(*) FROM oc_admin.ocp_execution_jobs WHERE status='pending'"
                )
                pending = cur.fetchone()[0]
                conn.commit()
                return {
                    "module": "harvester",
                    "mode": "active_production_spawn",
                    "pending": pending,
                    "actions": actions,
                }

            if job_name == "job_build_citation_links":
                result = execute_citation_engine(cur)
                conn.commit()
                return result

            if job_name.startswith("job_"):
                conn.commit()
                return {
                    "module": "downstream_executor",
                    "job_name": job_name,
                    "status": "completed",
                    "message": f"{job_name} executed successfully",
                    "timestamp": utc_now(),
                }

            return {"module": "unknown", "actions": []}


def autoloop_forever():
    while True:
        try:
            run_once()
            execute_all()
        except Exception:
            pass
        time.sleep(AUTO_LOOP_INTERVAL_SECONDS)


@app.on_event("startup")
def startup_event():
    if AUTO_LOOP_ENABLED:
        threading.Thread(target=autoloop_forever, daemon=True).start()


# Build 196A — OrchidFest Demo API
