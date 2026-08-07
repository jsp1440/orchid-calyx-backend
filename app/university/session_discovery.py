from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .durable_config import durable_sessions_enabled
from .durable_repository import DurableUniversityError, database_url


def _encode_cursor(updated_at: datetime, session_id: object) -> str:
    payload = {
        "updated_at": updated_at.isoformat(),
        "session_id": str(UUID(str(session_id))),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        session_id = UUID(str(payload["session_id"]))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DurableUniversityError("INVALID_SESSION_CURSOR", "Session discovery cursor is invalid") from exc
    if updated_at.tzinfo is None:
        raise DurableUniversityError("INVALID_SESSION_CURSOR", "Session discovery cursor must include timezone")
    return updated_at, session_id


def _connect():
    return psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=10)


def list_owned_session_summaries(
    *, actor: str, limit: int = 20, cursor: str | None = None
) -> dict[str, Any]:
    """Return only learner-owned session metadata using keyset pagination.

    Event payloads and review records are intentionally excluded. Ownership is
    enforced inside the SQL query rather than by post-query application filtering.
    """
    if not durable_sessions_enabled():
        raise DurableUniversityError(
            "DURABLE_UNIVERSITY_DISABLED",
            "Session discovery requires verified durable University activation",
        )
    if not actor.strip():
        raise DurableUniversityError("AUTHENTICATED_SUBJECT_REQUIRED", "Learner actor is required")
    if limit < 1 or limit > 50:
        raise DurableUniversityError("INVALID_SESSION_LIST_LIMIT", "Session list limit must be between 1 and 50")

    keyset = _decode_cursor(cursor)
    params: list[object] = [actor]
    where = "learner_actor=%s"
    if keyset is not None:
        updated_at, session_id = keyset
        where += " AND (updated_at, session_id) < (%s, %s)"
        params.extend([updated_at, session_id])
    params.append(limit + 1)

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT session_id, laboratory_id, chapter_id, status, current_stage,
                   revision, created_at, updated_at
            FROM oc_university.lab_sessions
            WHERE {where}
            ORDER BY updated_at DESC, session_id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = list(cur.fetchall())

    has_more = len(rows) > limit
    visible = rows[:limit]
    next_cursor = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = _encode_cursor(last["updated_at"], last["session_id"])

    return {
        "sessions": [
            {
                "session_id": str(row["session_id"]),
                "laboratory_id": row["laboratory_id"],
                "chapter_id": row["chapter_id"],
                "status": row["status"],
                "current_stage": row["current_stage"],
                "revision": int(row["revision"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in visible
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
