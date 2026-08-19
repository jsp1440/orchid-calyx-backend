"""GRAPH-001B: persisted analysis-run records for the Graph Intelligence Engine.

Wraps ``runtime.autonomous_runner``'s existing DB-backed job framework - no new
queue, no new table. A GRAPH-001A analytics result (already computed by
``bounded_snapshot``/``connected_components``/``degree``/``shortest_path``) is
recorded as a durable ``oc_admin.ocp_execution_jobs`` row; nothing here
recomputes or mutates the underlying graph, matching GRAPH-001A's own
read-only contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import psycopg

from runtime.autonomous_runner import (
    ensure_database_url,
    ensure_execution_jobs_table,
    insert_job_if_missing,
)

GRAPH_ANALYSIS_JOB_PREFIX = "graph_analysis:"


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def graph_analysis_dedup_key(*, algorithm: str, scope: str, parameters: dict[str, Any]) -> str:
    """The stable identity of one (algorithm, scope, parameters) analysis run.

    Used as both ``job_name`` and ``dedup_key`` in the underlying job row, so
    ``runtime.autonomous_runner.run_job_logic`` can re-fetch this exact run's
    stored details by job_name alone without any framework signature change.
    """
    if not algorithm.strip():
        raise ValueError("GRAPH_ANALYSIS_ALGORITHM_REQUIRED")
    if not scope.strip():
        raise ValueError("GRAPH_ANALYSIS_SCOPE_REQUIRED")
    return f"{GRAPH_ANALYSIS_JOB_PREFIX}{algorithm}:{scope}:{_stable_hash(parameters)}"


def record_graph_analysis_run(
    *,
    algorithm: str,
    parameters: dict[str, Any],
    scope: str,
    result_summary: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Persist a completed GRAPH-001A analysis result as a durable, queryable run.

    Takes an already-computed result - this function performs no graph
    traversal or recomputation itself. Idempotent: re-recording the identical
    (algorithm, scope, parameters) combination is a no-op on the second call
    (``recorded`` is ``False``), since ``oc_admin.ocp_execution_jobs.dedup_key``
    is unique and ``insert_job_if_missing`` already fails closed on conflict.
    """
    dedup_key = graph_analysis_dedup_key(algorithm=algorithm, scope=scope, parameters=parameters)
    details = {
        "algorithm": algorithm,
        "parameters": parameters,
        "scope": scope,
        "result_summary": result_summary,
        "warnings": list(warnings or []),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    with psycopg.connect(ensure_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_execution_jobs_table(cur)
            inserted = insert_job_if_missing(
                cur,
                job_name=dedup_key,
                dedup_key=dedup_key,
                details=details,
            )
        conn.commit()

    return {"recorded": inserted, "dedup_key": dedup_key}
