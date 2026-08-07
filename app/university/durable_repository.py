from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .durable_config import durable_sessions_enabled

_STAGE_ORDER = {
    "observe": 0,
    "question": 1,
    "investigate": 2,
    "analyze": 3,
    "interpret": 4,
    "communicate": 5,
    "contribute": 6,
}
_STAGE_STATUS = {
    "observe": "observing",
    "question": "questioning",
    "investigate": "investigating",
    "analyze": "analyzing",
    "interpret": "interpreting",
    "communicate": "communicating",
    "contribute": "submitted",
}


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
    """Append one learner event with stage checks and optimistic concurrency."""
    _require_gate()
    event_id = uuid.uuid4()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, learner_actor, revision, status, current_stage
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
        if current["status"] in {"submitted", "under_review", "approved_for_learning", "archived"}:
            raise DurableUniversityError("SESSION_LOCKED", "Session no longer accepts learner events")
        if current["revision"] != expected_revision:
            raise DurableUniversityError(
                "REVISION_CONFLICT",
                f"Expected revision {expected_revision}, found {current['revision']}",
            )
        current_index = _STAGE_ORDER[current["current_stage"]]
        requested_index = _STAGE_ORDER[stage]
        if requested_index < current_index or requested_index > current_index + 1:
            raise DurableUniversityError(
                "INVALID_STAGE_TRANSITION",
                "Events may remain in the current stage or advance exactly one stage",
            )
        if stage == "contribute":
            raise DurableUniversityError(
                "SUBMISSION_ENDPOINT_REQUIRED",
                "The contribute transition must use the explicit submission endpoint",
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
            SET revision=%s, current_stage=%s, status=%s, updated_at=NOW()
            WHERE session_id=%s AND revision=%s
            RETURNING *
            """,
            (next_revision, stage, _STAGE_STATUS[stage], session_id, expected_revision),
        )
        updated = cur.fetchone()
        if updated is None:
            raise DurableUniversityError("REVISION_CONFLICT", "Concurrent update prevented event append")
        return dict(updated)


def submit_session(*, session_id: str, actor: str, expected_revision: int) -> dict[str, Any]:
    """Submit a learner session for human review as an atomic revisioned event."""
    _require_gate()
    event_id = uuid.uuid4()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT learner_actor, revision, status, current_stage
            FROM oc_university.lab_sessions
            WHERE session_id=%s FOR UPDATE
            """,
            (session_id,),
        )
        current = cur.fetchone()
        if current is None:
            raise DurableUniversityError("SESSION_NOT_FOUND", "Session not found")
        if current["learner_actor"] != actor:
            raise DurableUniversityError("SESSION_FORBIDDEN", "Session belongs to another learner")
        if current["revision"] != expected_revision:
            raise DurableUniversityError("REVISION_CONFLICT", "Submission revision is stale")
        if current["status"] in {"submitted", "under_review", "approved_for_learning", "archived"}:
            raise DurableUniversityError("SESSION_LOCKED", "Session has already left learner editing")
        if _STAGE_ORDER[current["current_stage"]] < _STAGE_ORDER["communicate"]:
            raise DurableUniversityError(
                "SUBMISSION_NOT_READY",
                "A session must reach communicate before it can be submitted",
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
            VALUES (%s,%s,%s,'session_submitted','contribute','{}'::jsonb,%s,%s)
            """,
            (event_id, session_id, sequence_no, actor, next_revision),
        )
        cur.execute(
            """
            UPDATE oc_university.lab_sessions
            SET revision=%s, current_stage='contribute', status='submitted', updated_at=NOW()
            WHERE session_id=%s AND revision=%s
            RETURNING *
            """,
            (next_revision, session_id, expected_revision),
        )
        updated = cur.fetchone()
        if updated is None:
            raise DurableUniversityError("REVISION_CONFLICT", "Concurrent update prevented submission")
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
            "SELECT revision, status FROM oc_university.lab_sessions WHERE session_id=%s FOR UPDATE",
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
        if current["status"] not in {"submitted", "under_review"}:
            raise DurableUniversityError(
                "INVALID_REVIEW_STATE",
                "Only submitted or under-review sessions may receive an instructor decision",
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
        next_status = "changes_requested" if decision == "changes_requested" else "approved_for_learning"
        cur.execute(
            """
            UPDATE oc_university.lab_sessions
            SET status=%s, updated_at=NOW()
            WHERE session_id=%s
            """,
            (next_status, session_id),
        )
        return dict(review)
