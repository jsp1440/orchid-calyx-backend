from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.intake.repository import database_url


def create_action(source_id: int, payload: Any) -> dict[str, Any] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM oc_intake.sources WHERE id=%s", (source_id,))
            source = cur.fetchone()
            if not source or source["status"] not in ("APPROVED", "PUBLISHED"):
                return None
            cur.execute(
                """
                INSERT INTO oc_workflow.actions
                    (source_id, action_type, destination, title, description, owner,
                     priority, due_at, reminder_at, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    source_id, payload.action_type, payload.destination, payload.title,
                    payload.description, payload.owner, payload.priority, payload.due_at,
                    payload.reminder_at, Jsonb(payload.metadata),
                ),
            )
            action = cur.fetchone()
            cur.execute(
                """INSERT INTO oc_workflow.routing_history
                   (source_id, action_id, event_type, actor, notes)
                   VALUES (%s,%s,'ROUTED',%s,%s)""",
                (source_id, action["id"], payload.owner, payload.notes),
            )
            return action


def list_actions(*, source_id: int | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_id is not None:
        clauses.append("a.source_id=%s")
        params.append(source_id)
    if status is not None:
        clauses.append("a.status=%s")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT a.*, s.title AS source_title
                    FROM oc_workflow.actions a
                    JOIN oc_intake.sources s ON s.id=a.source_id
                    {where}
                    ORDER BY COALESCE(a.due_at, 'infinity'::timestamptz), a.created_at DESC
                    LIMIT %s""",
                params,
            )
            return list(cur.fetchall())


def update_action(action_id: int, status: str, notes: str | None, actor: str | None) -> dict[str, Any] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE oc_workflow.actions
                SET status=%s, updated_at=NOW(),
                    completed_at=CASE WHEN %s='COMPLETED' THEN NOW() ELSE completed_at END
                WHERE id=%s RETURNING *
                """,
                (status, status, action_id),
            )
            action = cur.fetchone()
            if not action:
                return None
            cur.execute(
                """INSERT INTO oc_workflow.routing_history
                   (source_id, action_id, event_type, actor, notes)
                   VALUES (%s,%s,%s,%s,%s)""",
                (action["source_id"], action_id, f"STATUS_{status}", actor, notes),
            )
            return action


def source_workflow(source_id: int) -> dict[str, Any] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, status FROM oc_intake.sources WHERE id=%s", (source_id,))
            source = cur.fetchone()
            if not source:
                return None
            cur.execute("SELECT * FROM oc_workflow.actions WHERE source_id=%s ORDER BY created_at", (source_id,))
            source["actions"] = list(cur.fetchall())
            cur.execute("SELECT * FROM oc_workflow.routing_history WHERE source_id=%s ORDER BY event_at", (source_id,))
            source["history"] = list(cur.fetchall())
            return source
