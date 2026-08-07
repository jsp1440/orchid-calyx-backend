from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.mission_control_access import AccessPrincipal, Capability, CapabilityService

from .activation_service import qualified_reviewer_context
from .durable_config import durable_sessions_enabled
from .durable_repository import DurableUniversityError, database_url
from .service import UniversityServiceError
from .session_discovery import _decode_cursor, _encode_cursor

_SCIENTIFIC_QUALIFICATIONS = frozenset(
    {
        "qualified.science-reviewer",
        "qualified.expert-reviewer",
        "qualified.publication-reviewer",
    }
)
_capabilities = CapabilityService()


def reviewer_context(principal: AccessPrincipal) -> dict[str, Any]:
    effective = set(_capabilities.effective_capabilities(principal))
    scientific_qualifications = sorted(
        qualification
        for qualification in principal.qualifications
        if qualification in _SCIENTIFIC_QUALIFICATIONS
    )
    return {
        "principal_id": principal.principal_id,
        "authenticated": principal.authenticated,
        "roles": [role.value for role in principal.roles],
        "qualifications": scientific_qualifications,
        "specialties": list(principal.specialties),
        "effective_capabilities": sorted(effective),
        "science_review_allowed": (
            Capability.REVIEW_SCIENCE.value in effective and bool(scientific_qualifications)
        ),
        "expert_review_allowed": (
            Capability.REVIEW_EXPERT.value in effective and bool(scientific_qualifications)
        ),
        "durable_sessions_enabled": durable_sessions_enabled(),
        "governance": {
            "administrator_role_does_not_imply_scientific_authority": True,
            "learner_identity_does_not_imply_reviewer_authority": True,
            "publication_performed": False,
            "candidate_knowledge_promoted": False,
        },
    }


def require_science_reviewer(principal: AccessPrincipal) -> dict[str, object]:
    """Use the same authorization rule as a changes-requested/learning decision."""
    return qualified_reviewer_context(principal, "changes_requested")


def _require_durable() -> None:
    if not durable_sessions_enabled():
        raise DurableUniversityError(
            "DURABLE_UNIVERSITY_DISABLED",
            "University reviewer workspace requires verified durable-session activation",
        )


def _connect():
    return psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=10)


def list_reviewable_session_summaries(
    *, principal: AccessPrincipal, limit: int = 20, cursor: str | None = None
) -> dict[str, Any]:
    require_science_reviewer(principal)
    _require_durable()
    if limit < 1 or limit > 50:
        raise DurableUniversityError(
            "INVALID_REVIEW_QUEUE_LIMIT", "Reviewer queue limit must be between 1 and 50"
        )

    keyset = _decode_cursor(cursor)
    params: list[object] = []
    where = "status IN ('submitted','under_review')"
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


def reviewer_session_detail(
    *, principal: AccessPrincipal, session_id: str
) -> dict[str, Any]:
    require_science_reviewer(principal)
    _require_durable()

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, laboratory_id, chapter_id, status, current_stage,
                   revision, created_at, updated_at
            FROM oc_university.lab_sessions
            WHERE session_id=%s
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise DurableUniversityError("SESSION_NOT_FOUND", "Session not found")
        if row["status"] not in {"submitted", "under_review"}:
            raise DurableUniversityError(
                "INVALID_REVIEW_STATE",
                "Only submitted or under-review sessions are visible in the reviewer workspace",
            )

        cur.execute(
            """
            SELECT event_id, event_type, stage, payload, session_revision, created_at
            FROM oc_university.session_events
            WHERE session_id=%s
            ORDER BY sequence_no
            """,
            (session_id,),
        )
        events = [dict(event) for event in cur.fetchall()]

        cur.execute(
            """
            SELECT decision, notes, reviewed_revision, reviewer_capability, created_at
            FROM oc_university.session_reviews
            WHERE session_id=%s
            ORDER BY created_at, review_id
            """,
            (session_id,),
        )
        reviews = [dict(review) for review in cur.fetchall()]

    return {
        "session_id": str(row["session_id"]),
        "laboratory_id": row["laboratory_id"],
        "chapter_id": row["chapter_id"],
        "status": row["status"],
        "current_stage": row["current_stage"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "events": [
            {
                "event_id": str(event["event_id"]),
                "event_type": event["event_type"],
                "stage": event["stage"],
                "payload": event.get("payload") or {},
                "session_revision": int(event["session_revision"]),
                "created_at": event["created_at"],
            }
            for event in events
        ],
        "review_history": [
            {
                "decision": review["decision"],
                "notes": review.get("notes"),
                "reviewed_revision": int(review["reviewed_revision"]),
                "reviewer_capability": review["reviewer_capability"],
                "created_at": review["created_at"],
            }
            for review in reviews
        ],
        "privacy": {
            "learner_actor_exposed": False,
            "event_actor_exposed": False,
            "reviewer_actor_exposed": False,
        },
    }
