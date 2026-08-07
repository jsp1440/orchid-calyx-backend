from __future__ import annotations

import os
import uuid
from typing import Any, Iterable

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
_EVENT_STAGE = {
    "observation_added": "observe",
    "question_set": "question",
    "hypothesis_added": "investigate",
    "evidence_examined": "investigate",
    "analysis_recorded": "analyze",
    "interpretation_recorded": "interpret",
    "conclusion_drafted": "communicate",
    "uncertainty_recorded": "communicate",
}
_STAGE_EXIT_REQUIREMENTS: dict[str, frozenset[str]] = {
    "observe": frozenset({"observation_added"}),
    "question": frozenset({"question_set"}),
    "investigate": frozenset({"hypothesis_added", "evidence_examined"}),
    "analyze": frozenset({"analysis_recorded"}),
    "interpret": frozenset({"interpretation_recorded"}),
    "communicate": frozenset({"conclusion_drafted", "uncertainty_recorded"}),
}


class DurableUniversityError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def missing_stage_requirements(stage: str, event_types: Iterable[str]) -> tuple[str, ...]:
    required = _STAGE_EXIT_REQUIREMENTS.get(stage, frozenset())
    present = set(event_types)
    return tuple(sorted(required - present))


def validate_event_stage(event_type: str, requested_stage: str, current_stage: str) -> None:
    if event_type == "stage_advanced":
        expected_index = _STAGE_ORDER[current_stage] + 1
        if expected_index >= len(_STAGE_ORDER) or _STAGE_ORDER[requested_stage] != expected_index:
            raise DurableUniversityError(
                "INVALID_STAGE_TRANSITION",
                "stage_advanced must advance exactly one inquiry stage",
            )
        return
    expected_stage = _EVENT_STAGE.get(event_type)
    if expected_stage is None:
        raise DurableUniversityError("INVALID_EVENT_TYPE", "Unsupported learner event type")
    if requested_stage != current_stage or expected_stage != current_stage:
        raise DurableUniversityError(
            "EVENT_STAGE_MISMATCH",
            f"{event_type} belongs to {expected_stage}, not {requested_stage}",
        )


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


def _event_types_for_stage(cur, session_id: str, stage: str, *, after_revision: int = 0) -> set[str]:
    cur.execute(
        """
        SELECT event_type
        FROM oc_university.session_events
        WHERE session_id=%s AND stage=%s AND session_revision>%s
        """,
        (session_id, stage, after_revision),
    )
    return {str(row["event_type"]) for row in cur.fetchall()}


def _require_stage_complete(cur, session_id: str, stage: str, *, after_revision: int = 0) -> None:
    missing = missing_stage_requirements(
        stage,
        _event_types_for_stage(cur, session_id, stage, after_revision=after_revision),
    )
    if missing:
        raise DurableUniversityError(
            "STAGE_EXIT_REQUIREMENTS_UNMET",
            f"{stage} is missing required learner records: {', '.join(missing)}",
        )


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
    """Append one learner event with semantic stage gates and optimistic concurrency."""
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
        if stage == "contribute":
            raise DurableUniversityError(
                "SUBMISSION_ENDPOINT_REQUIRED",
                "The contribute transition must use the explicit submission endpoint",
            )

        validate_event_stage(event_type, stage, current["current_stage"])
        if event_type == "stage_advanced":
            _require_stage_complete(cur, session_id, current["current_stage"])

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
    """Submit a complete communicate stage for human review as a revisioned event."""
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
        if current["current_stage"] != "communicate":
            raise DurableUniversityError(
                "SUBMISSION_NOT_READY",
                "A session must be in communicate before it can be submitted",
            )

        cur.execute(
            """
            SELECT decision, reviewed_revision
            FROM oc_university.session_reviews
            WHERE session_id=%s
            ORDER BY created_at DESC, review_id DESC
            LIMIT 1
            """,
            (session_id,),
        )
        latest_review = cur.fetchone()
        after_revision = 0
        if latest_review and latest_review["decision"] == "changes_requested":
            after_revision = int(latest_review["reviewed_revision"])
            if current["revision"] <= after_revision:
                raise DurableUniversityError(
                    "CHANGES_NOT_ADDRESSED",
                    "A changes-requested session must contain a new learner revision before resubmission",
                )

        _require_stage_complete(cur, session_id, "communicate", after_revision=after_revision)

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
    reviewer_capability: str,
    reviewer_roles: tuple[str, ...],
    reviewer_qualifications: tuple[str, ...],
    reviewed_revision: int,
    decision: str,
    notes: str | None,
) -> dict[str, Any]:
    """Record qualified human review without publication or Candidate Knowledge writes."""
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
                (review_id, session_id, reviewer_actor, reviewer_capability,
                 reviewer_roles, reviewer_qualifications, decision, notes, reviewed_revision)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
            """,
            (
                review_id,
                session_id,
                reviewer_actor,
                reviewer_capability,
                Jsonb(list(reviewer_roles)),
                Jsonb(list(reviewer_qualifications)),
                decision,
                notes,
                reviewed_revision,
            ),
        )
        review = cur.fetchone()
        if review is None:
            raise DurableUniversityError("REVIEW_CREATE_FAILED", "Review insert returned no row")
        if decision == "changes_requested":
            cur.execute(
                """
                UPDATE oc_university.lab_sessions
                SET status='changes_requested', current_stage='communicate', updated_at=NOW()
                WHERE session_id=%s
                """,
                (session_id,),
            )
        else:
            cur.execute(
                """
                UPDATE oc_university.lab_sessions
                SET status='approved_for_learning', updated_at=NOW()
                WHERE session_id=%s
                """,
                (session_id,),
            )
        return dict(review)
