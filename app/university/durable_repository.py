from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .durable_config import durable_sessions_enabled


class DurableUniversityError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise DurableUniversityError("DATABASE_URL_REQUIRED", "DATABASE_URL is required")
    return value


def _require_gate() -> None:
    if not durable_sessions_enabled():
        raise DurableUniversityError(
            "DURABLE_UNIVERSITY_DISABLED",
            "Durable University sessions are not enabled by the post-cutover release gate",
        )


def _connect():
    return psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=10)


def create_session(*, laboratory_id: str, chapter_id: str, learner_actor: str) -> dict[str, Any]:
    _require_gate()
    session_id = uuid.uuid4()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_university.lab_sessions
                (session_id, laboratory_id, chapter_id, learner_actor, status, current_stage)
            VALUES (%s, %s, %s, %s, 'created', 'observe')
            RETURNING *
            """,
            (session_id, laboratory_id, chapter_id, learner_actor),
        )
        row = cur.fetchone()
        if row is None:
            raise DurableUniversityError("SESSION_CREATE_FAILED", "Session insert returned no row")
        return dict(row)


def get_session(*, session_id: str, actor: str, privileged: bool = False) -> dict[str, Any]:
    _require_gate()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM oc_university.lab_sessions WHERE session_id=%s", (session_id,))
        row = cur.fetchone()
        if row is None:
            raise DurableUniversityError("SESSION_NOT_FOUND", "Session not found")
        if not privileged and row["learner_actor"] != actor:
            raise DurableUniversityError("SESSION_FORBIDDEN", "Session belongs to another learner")
        cur.execute(
            "SELECT * FROM oc_university.session_events WHERE session_id=%s ORDER BY sequence_no",
            (session_id,),
        )
        result = dict(row)
        result["events"] = list(cur.fetchall())
        return result


def append_event(
    *,
    session_id: str,
    actor: str,
    expected_revision: int,
    event_type: str,
    stage: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Append one event with optimistic concurrency.

    The caller must present the revision it last observed. A stale revision produces
    `REVISION_CONFLICT` and writes nothing.
    """
    _require_gate()
    event_id = uuid.uuid4()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, learner_actor, revision
            FROM oc_university.lab_sessions
            WHERE session_id=%s
            FOR UPDATE
            """,
            (session_id,),
        )
        current = cur.fetchone()
        if current is None:
            raise DurableUniversityError("SESSION_NOT_FOUND", "Session not found")
        if current["learner_actor"] != actor:
            raise DurableUniversityError("SESSION_FORBIDDEN", "Session belongs to another learner")
        if current["revision"] != expected_revision:
            raise DurableUniversityError(
                "REVISION_CONFLICT",
                f"Expected revision {expected_revision}, found {current['revision']}",
            )

        next_revision = expected_revision + 1
        cur.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence FROM oc_university.session_events WHERE session_id=%s",
            (session_id,),
        )
        sequence_no = int(cur.fetchone()["next_sequence"])
        cur.execute(
            """
            INSERT INTO oc_university.session_events
                (event_id, session_id, sequence_no, event_type, stage, payload, actor, session_revision)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (event_id, session_id, sequence_no, event_type, stage, Jsonb(payload), actor, next_revision),
        )
        cur.execute(
            """
            UPDATE oc_university.lab_sessions
            SET revision=%s, updated_at=NOW()
            WHERE session_id=%s AND revision=%s
            RETURNING *
            """,
            (next_revision, session_id, expected_revision),
        )
        updated = cur.fetchone()
        if updated is None:
            raise DurableUniversityError("REVISION_CONFLICT", "Concurrent update prevented event append")
        return dict(updated)


def record_review(
    *,
    session_id: str,
    reviewer_actor: str,
    reviewed_revision: int,
    decision: str,
    notes: str | None,
) -> dict[str, Any]:
    """Record human review without performing publication or Candidate Knowledge writes."""
    _require_gate()
    review_id = uuid.uuid4()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT revision FROM oc_university.lab_sessions WHERE session_id=%s FOR UPDATE",
            (session_id,),
        )
        current = cur.fetchone()
        if current is None:
            raise DurableUniversityError("SESSION_NOT_FOUND", "Session not found")
        if current["revision"] != reviewed_revision:
            raise DurableUniversityError(
                "REVISION_CONFLICT",
                "Review must target the learner revision that was actually inspected",
            )
        cur.execute(
            """
            INSERT INTO oc_university.session_reviews
                (review_id, session_id, reviewer_actor, decision, notes, reviewed_revision)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING *
            """,
            (review_id, session_id, reviewer_actor, decision, notes, reviewed_revision),
        )
        review = cur.fetchone()
        if review is None:
            raise DurableUniversityError("REVIEW_CREATE_FAILED", "Review insert returned no row")
        return dict(review)
