"""Optional BUILD-105 PostgreSQL persistence for harvester safety telemetry.

All functions fail closed and become no-ops when DATABASE_URL is absent or the
BUILD-105 migration has not been applied. This lets code ship before migration
approval without breaking workers or preview endpoints.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("harvesters.safety_store")


def _connect():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None
    try:
        import psycopg2
        return psycopg2.connect(database_url)
    except Exception as exc:
        log.warning("harvester safety store unavailable: %s", exc)
        return None


def record_safety_snapshot(
    harvester_id: str,
    *,
    cursor: Any,
    mode: str,
    budget: dict[str, Any],
    audit: dict[str, Any],
    circuit_open: bool = False,
    circuit_reason: str | None = None,
) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_admin.harvest_safety_state
                    (harvester_id, last_cursor, circuit_open, circuit_reason,
                     last_run_mode, last_budget, last_audit, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (harvester_id) DO UPDATE SET
                    last_cursor = EXCLUDED.last_cursor,
                    circuit_open = EXCLUDED.circuit_open,
                    circuit_reason = EXCLUDED.circuit_reason,
                    last_run_mode = EXCLUDED.last_run_mode,
                    last_budget = EXCLUDED.last_budget,
                    last_audit = EXCLUDED.last_audit,
                    updated_at = now()
                """,
                (
                    harvester_id,
                    None if cursor is None else str(cursor),
                    circuit_open,
                    circuit_reason,
                    mode,
                    json.dumps(budget, default=str),
                    json.dumps(audit, default=str),
                ),
            )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        log.warning("harvester safety snapshot not persisted: %s", exc)
        return False
    finally:
        conn.close()


def record_dead_letter(
    harvester_id: str,
    *,
    source_record_id: Any,
    reason: str,
    payload: dict[str, Any],
) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_admin.harvest_dead_letter
                    (harvester_id, source_record_id, reason, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    harvester_id,
                    None if source_record_id is None else str(source_record_id),
                    reason,
                    json.dumps(payload, default=str),
                ),
            )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        log.warning("harvester dead letter not persisted: %s", exc)
        return False
    finally:
        conn.close()
