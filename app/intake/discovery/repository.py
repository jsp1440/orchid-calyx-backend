"""Durable state for native discovery: runs, cursors, records, verification."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..repository import database_url
from . import DISCOVERY_VERSION
from .records import DiscoveredWork, normalize_title

TERMINAL_RUN_STATES = ("COMPLETED", "NO_WORK")
RESUMABLE_RUN_STATES = ("PARTIAL", "FAILED", "INTERRUPTED")


def _connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), row_factory=dict_row)


def _lock_key(run_key: str) -> int:
    return int.from_bytes(
        sha256(f"oc-discovery:{run_key}".encode()).digest()[:8], "big", signed=True
    )


def start_run(
    *,
    run_key: str,
    mode: str,
    profiles: list[str],
    budget: dict[str, Any],
    stale_after: timedelta = timedelta(hours=2),
) -> dict[str, Any]:
    """Claim a run attempt idempotently.

    Returns ``{"claimed": True, "run": ...}`` for a new attempt, or
    ``{"claimed": False, "reason": ..., "run": ...}`` when the key already
    completed or a live attempt still holds it.  A RUNNING attempt older than
    ``stale_after`` is recorded as INTERRUPTED and superseded, so a crashed
    worker never wedges discovery and never has its work marked complete.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_lock_key(run_key),))
        cur.execute(
            "SELECT * FROM oc_intake.discovery_runs WHERE run_key=%s ORDER BY attempt DESC LIMIT 1",
            (run_key,),
        )
        latest = cur.fetchone()
        if latest is not None:
            if latest["status"] in TERMINAL_RUN_STATES:
                return {
                    "claimed": False,
                    "reason": "RUN_KEY_ALREADY_COMPLETED",
                    "run": latest,
                }
            if latest["status"] == "RUNNING":
                cur.execute(
                    "SELECT NOW() - %s::timestamptz > %s AS stale",
                    (latest["started_at"], stale_after),
                )
                if not cur.fetchone()["stale"]:
                    return {
                        "claimed": False,
                        "reason": "RUN_IN_PROGRESS",
                        "run": latest,
                    }
                cur.execute(
                    """
                    UPDATE oc_intake.discovery_runs
                    SET status='INTERRUPTED', finished_at=NOW(),
                        failure_reasons = failure_reasons || %s
                    WHERE id=%s
                    """,
                    (
                        Jsonb(
                            [
                                {
                                    "code": "STALE_RUN_INTERRUPTED",
                                    "detail": "Attempt exceeded its lease and was superseded.",
                                }
                            ]
                        ),
                        latest["id"],
                    ),
                )
        attempt = 1 if latest is None else int(latest["attempt"]) + 1
        cur.execute(
            """
            INSERT INTO oc_intake.discovery_runs
                (run_key, attempt, mode, status, profiles, budget, discovery_version)
            VALUES (%s,%s,%s,'RUNNING',%s,%s,%s)
            RETURNING *
            """,
            (run_key, attempt, mode, Jsonb(profiles), Jsonb(budget), DISCOVERY_VERSION),
        )
        return {"claimed": True, "run": cur.fetchone()}


def finish_run(
    run_id: int,
    *,
    status: str,
    usage: dict[str, Any],
    counts: dict[str, Any],
    provider_results: list[dict[str, Any]],
    zero_work_reason: str | None,
    failure_reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE oc_intake.discovery_runs
            SET status=%s, finished_at=NOW(), usage=%s, counts=%s, provider_results=%s,
                zero_work_reason=%s, failure_reasons=failure_reasons || %s
            WHERE id=%s AND status='RUNNING'
            RETURNING *
            """,
            (
                status,
                Jsonb(usage),
                Jsonb(counts),
                Jsonb(provider_results),
                zero_work_reason,
                Jsonb(failure_reasons),
                run_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("DISCOVERY_RUN_NOT_RUNNING")
        return row


def get_cursor(profile_key: str, provider: str) -> dict[str, Any] | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM oc_intake.discovery_cursors WHERE profile_key=%s AND provider=%s",
            (profile_key, provider),
        )
        return cur.fetchone()


def advance_cursor(
    profile_key: str, provider: str, *, watermark: date, run_id: int
) -> None:
    """Advance only forward; a historical backfill never rewinds the live cursor."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_intake.discovery_cursors
                (profile_key, provider, watermark, last_run_id, last_success_at, last_error, consecutive_failures)
            VALUES (%s,%s,%s,%s,NOW(),NULL,0)
            ON CONFLICT (profile_key, provider) DO UPDATE SET
                watermark = GREATEST(oc_intake.discovery_cursors.watermark, EXCLUDED.watermark),
                last_run_id = EXCLUDED.last_run_id,
                last_success_at = NOW(),
                last_error = NULL,
                consecutive_failures = 0,
                updated_at = NOW()
            """,
            (profile_key, provider, watermark, run_id),
        )


def record_cursor_failure(
    profile_key: str, provider: str, *, error: str, run_id: int
) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_intake.discovery_cursors
                (profile_key, provider, last_run_id, last_error, consecutive_failures)
            VALUES (%s,%s,%s,%s,1)
            ON CONFLICT (profile_key, provider) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id,
                last_error = EXCLUDED.last_error,
                consecutive_failures = oc_intake.discovery_cursors.consecutive_failures + 1,
                updated_at = NOW()
            """,
            (profile_key, provider, run_id, error[:2000]),
        )


def previous_metadata_sha256(provider: str, provider_record_id: str) -> str | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT metadata_sha256 FROM oc_intake.discovery_records WHERE provider=%s AND provider_record_id=%s",
            (provider, provider_record_id),
        )
        row = cur.fetchone()
        return str(row["metadata_sha256"]) if row else None


def find_identity(doi: str | None, title: str) -> dict[str, Any] | None:
    """Resolve a source to an existing ledger item: DOI first, then exact title."""
    with _connect() as conn, conn.cursor() as cur:
        if doi:
            cur.execute(
                """
                SELECT i.id AS intelligence_item_id, i.knowledge_fingerprint, i.domain
                FROM oc_intake.discovery_records r
                JOIN oc_intake.intelligence_items i ON i.id = r.intelligence_item_id
                WHERE r.doi = %s ORDER BY r.id LIMIT 1
                """,
                (doi,),
            )
            row = cur.fetchone()
            if row:
                return row
            # Items recorded by other intake paths (e.g. a briefing that cited the DOI).
            cur.execute(
                """
                SELECT id AS intelligence_item_id, knowledge_fingerprint, domain
                FROM oc_intake.intelligence_items
                WHERE EXISTS (
                    SELECT 1 FROM jsonb_array_elements_text(dois) AS cited(doi)
                    WHERE lower(cited.doi) = %s
                )
                ORDER BY id LIMIT 1
                """,
                (doi.lower(),),
            )
            row = cur.fetchone()
            if row:
                return row
            return None
        cur.execute(
            """
            SELECT i.id AS intelligence_item_id, i.knowledge_fingerprint, i.domain
            FROM oc_intake.discovery_records r
            JOIN oc_intake.intelligence_items i ON i.id = r.intelligence_item_id
            WHERE r.normalized_title = %s AND r.doi IS NULL ORDER BY r.id LIMIT 1
            """,
            (normalize_title(title),),
        )
        return cur.fetchone()


def upsert_discovery_record(
    *,
    intelligence_item_id: int,
    work: DiscoveredWork,
    profile_key: str,
    novelty: str,
    run_id: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_intake.discovery_records
                (intelligence_item_id, provider, provider_record_id, doi, title, normalized_title,
                 source_published_on, source_date_precision, first_run_id, last_run_id,
                 profile_key, novelty, metadata_sha256, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (provider, provider_record_id) DO UPDATE SET
                doi = EXCLUDED.doi,
                title = EXCLUDED.title,
                normalized_title = EXCLUDED.normalized_title,
                source_published_on = EXCLUDED.source_published_on,
                source_date_precision = EXCLUDED.source_date_precision,
                last_discovered_at = NOW(),
                last_run_id = EXCLUDED.last_run_id,
                novelty = EXCLUDED.novelty,
                update_count = oc_intake.discovery_records.update_count
                    + CASE WHEN oc_intake.discovery_records.metadata_sha256 <> EXCLUDED.metadata_sha256 THEN 1 ELSE 0 END,
                metadata_sha256 = EXCLUDED.metadata_sha256,
                metadata = EXCLUDED.metadata
            RETURNING id, novelty, update_count, first_discovered_at
            """,
            (
                intelligence_item_id,
                work.provider,
                work.provider_record_id,
                work.doi,
                work.title,
                normalize_title(work.title),
                work.published_on,
                work.published_precision,
                run_id,
                run_id,
                profile_key,
                novelty,
                work.metadata_sha256(),
                Jsonb(metadata),
            ),
        )
        return cur.fetchone()


def get_verification_state(intelligence_item_id: int) -> dict[str, Any] | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM oc_intake.discovery_verification_states WHERE intelligence_item_id=%s",
            (intelligence_item_id,),
        )
        return cur.fetchone()


def set_verification_state(
    intelligence_item_id: int,
    *,
    state: str,
    basis: dict[str, Any],
    primary_source_attempted: bool,
) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_intake.discovery_verification_states
                (intelligence_item_id, verification_state, basis, primary_source_attempted_at)
            VALUES (%s,%s,%s,CASE WHEN %s THEN NOW() END)
            ON CONFLICT (intelligence_item_id) DO UPDATE SET
                verification_state = EXCLUDED.verification_state,
                basis = EXCLUDED.basis,
                primary_source_attempted_at = COALESCE(
                    EXCLUDED.primary_source_attempted_at,
                    oc_intake.discovery_verification_states.primary_source_attempted_at
                ),
                updated_at = NOW()
            """,
            (intelligence_item_id, state, Jsonb(basis), primary_source_attempted),
        )


def provider_views(intelligence_item_id: int) -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM oc_intake.discovery_records WHERE intelligence_item_id=%s ORDER BY provider, id",
            (intelligence_item_id,),
        )
        return list(cur.fetchall())


def digest_inputs(since: datetime, until: datetime) -> dict[str, Any]:
    """Read-only snapshot the digest builder renders.  No writes."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.domain, i.title, i.priority, i.lifecycle, i.knowledge_delta,
                   i.canonical_destinations, i.follow_up_tasks, i.source_urls, i.dois,
                   i.observation_count, i.first_seen_at, i.last_seen_at,
                   v.verification_state, v.basis AS verification_basis,
                   MIN(r.source_published_on) AS source_published_on,
                   MIN(r.first_discovered_at) AS first_discovered_at,
                   MAX(r.last_discovered_at) AS last_discovered_at,
                   ARRAY_AGG(DISTINCT r.provider) AS providers,
                   ARRAY_AGG(DISTINCT r.novelty) AS novelty_states,
                   SUM(r.update_count) AS update_count,
                   (ARRAY_AGG(r.metadata ORDER BY r.id))[1] AS metadata
            FROM oc_intake.discovery_records r
            JOIN oc_intake.intelligence_items i ON i.id = r.intelligence_item_id
            LEFT JOIN oc_intake.discovery_verification_states v ON v.intelligence_item_id = i.id
            WHERE r.last_discovered_at >= %s AND r.last_discovered_at < %s
            GROUP BY i.id, v.verification_state, v.basis
            ORDER BY i.id
            """,
            (since, until),
        )
        items = list(cur.fetchall())
        item_ids = [row["id"] for row in items]
        cur.execute(
            """
            SELECT intelligence_item_id, destination, route_status, updated_at
            FROM oc_intake.intelligence_routes WHERE intelligence_item_id = ANY(%s)
            ORDER BY intelligence_item_id, destination
            """,
            (item_ids,),
        )
        routes = list(cur.fetchall())
        cur.execute(
            """
            SELECT intelligence_item_id, action_type, status, destination, approval_required, rationale
            FROM oc_intake.intelligence_actions
            WHERE intelligence_item_id = ANY(%s) OR (approval_required AND status IN ('OPEN','WAITING_APPROVAL'))
            ORDER BY intelligence_item_id, action_type
            """,
            (item_ids,),
        )
        actions = list(cur.fetchall())
        cur.execute(
            """
            SELECT id, run_key, attempt, mode, status, started_at, finished_at, counts, usage,
                   zero_work_reason, failure_reasons
            FROM oc_intake.discovery_runs
            WHERE started_at >= %s AND started_at < %s
            ORDER BY started_at, id
            """,
            (since, until),
        )
        runs = list(cur.fetchall())
        cur.execute(
            "SELECT * FROM oc_intake.discovery_cursors WHERE consecutive_failures > 0 ORDER BY profile_key, provider"
        )
        failing_cursors = list(cur.fetchall())
    return {
        "items": items,
        "routes": routes,
        "actions": actions,
        "runs": runs,
        "failing_cursors": failing_cursors,
    }
