"""Internal autonomous execution for Calyx Intelligence Assimilation.

This module advances only side-effect-free internal stages. External source
retrieval remains with governed harvesters/retrievers; external contact and
canonical publication are never performed here.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .intelligence_verification import route_intelligence_item
from .knowledge_delta import assess_item
from .knowledge_delta_repository import record_comparison
from .repository import database_url

JOB_RE = re.compile(r"^calyx_intelligence_(compare|route)_(\d+)$")


def _ensure_jobs(cur: Any) -> None:
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_admin")
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
        )
        """
    )


def _insert(cur: Any, *, name: str, dedup: str, item_id: int, stage: str) -> bool:
    cur.execute(
        """
        INSERT INTO oc_admin.ocp_execution_jobs
            (job_name, dedup_key, status, details, updated_at)
        VALUES (%s,%s,'pending',%s,NOW())
        ON CONFLICT (dedup_key) DO NOTHING
        RETURNING id
        """,
        (name, dedup, Jsonb({"intelligence_item_id": item_id, "stage": stage})),
    )
    return cur.fetchone() is not None


def enqueue_due_intelligence_jobs(limit: int = 50) -> dict[str, Any]:
    """Create idempotent compare/route jobs from durable intelligence state."""
    created: list[str] = []
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            _ensure_jobs(cur)
            cur.execute(
                """
                SELECT id, lifecycle, knowledge_delta
                FROM oc_intake.intelligence_items
                WHERE canonical_promotion_prohibited=TRUE
                  AND external_contact_prohibited=TRUE
                  AND lifecycle NOT IN ('REJECTED','DUPLICATE','ACTIONED','ASSIMILATED')
                ORDER BY priority DESC, last_seen_at ASC, id ASC
                LIMIT %s
                """,
                (limit,),
            )
            for item in cur.fetchall():
                item_id = int(item["id"])
                if item["knowledge_delta"] == "UNASSESSED":
                    name = f"calyx_intelligence_compare_{item_id}"
                    if _insert(cur, name=name, dedup=f"intel:compare:{item_id}", item_id=item_id, stage="compare"):
                        created.append(name)
                    continue

                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM oc_intake.intelligence_verifications
                        WHERE intelligence_item_id=%s AND outcome='SOURCE_CONFIRMED'
                    ) AS source_confirmed
                    """,
                    (item_id,),
                )
                existence = cur.fetchone()
                if bool(existence["source_confirmed"]) and item["lifecycle"] != "ROUTED":
                    name = f"calyx_intelligence_route_{item_id}"
                    if _insert(cur, name=name, dedup=f"intel:route:{item_id}", item_id=item_id, stage="route"):
                        created.append(name)
        conn.commit()
    return {
        "status": "ok",
        "jobs_created": created,
        "external_retrieval_performed": False,
        "external_contacted": False,
        "canonical_graph_mutated": False,
    }


def execute_internal_intelligence_job(job_name: str) -> dict[str, Any] | None:
    """Execute recognized compare/route jobs; return None for unrelated jobs."""
    match = JOB_RE.match(job_name)
    if not match:
        return None
    stage, raw_id = match.groups()
    item_id = int(raw_id)
    if stage == "compare":
        result = record_comparison(assess_item(item_id))
    else:
        result = route_intelligence_item(item_id)
    return {
        "module": "calyx_intelligence",
        "stage": stage,
        "item_id": item_id,
        "status": "completed",
        "result": result,
        "external_retrieval_performed": False,
        "external_contacted": False,
        "canonical_graph_mutated": False,
    }
