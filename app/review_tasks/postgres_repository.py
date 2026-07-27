from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Protocol


class Cursor(Protocol):
    description: Any

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


ConnectionFactory = Callable[[], Connection]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


@contextmanager
def _transaction(factory: ConnectionFactory) -> Iterator[tuple[Connection, Cursor]]:
    connection = factory()
    cursor = connection.cursor()
    try:
        yield connection, cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def _row(cursor: Cursor, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: _decode(item) for key, item in value.items()}
    columns = [item[0] for item in cursor.description]
    return {key: _decode(item) for key, item in zip(columns, value)}


class PostgresReviewTaskRepository:
    """DB-API compatible authoritative repository for governed review records."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    def get(self, task_id: str) -> dict[str, Any] | None:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute("SELECT * FROM oc_review.review_task WHERE task_id = %s", (task_id,))
            return _row(cursor, cursor.fetchone())

    def save(self, task: dict[str, Any]) -> dict[str, Any]:
        values = deepcopy(task)
        values.pop("history", None)
        values.pop("decisions", None)
        values.pop("reused", None)
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                """
                INSERT INTO oc_review.review_task (
                    task_id, orchestration_id, review_type, risk_class, routing_outcome,
                    required_capability, candidate_ids, aggregate_version_ids, priority,
                    scientific_impact_score, consensus_required, batch_key, display_policy,
                    embargoed, metadata, state, assigned_to, reservation_expires_at,
                    authoritative_decision, created_at, updated_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,
                    %s::jsonb,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (task_id) DO UPDATE SET
                    priority = EXCLUDED.priority,
                    scientific_impact_score = EXCLUDED.scientific_impact_score,
                    consensus_required = EXCLUDED.consensus_required,
                    display_policy = EXCLUDED.display_policy,
                    embargoed = EXCLUDED.embargoed,
                    metadata = EXCLUDED.metadata,
                    state = EXCLUDED.state,
                    assigned_to = EXCLUDED.assigned_to,
                    reservation_expires_at = EXCLUDED.reservation_expires_at,
                    authoritative_decision = EXCLUDED.authoritative_decision,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                (
                    values["task_id"], values["orchestration_id"], values["review_type"],
                    values["risk_class"], values["routing_outcome"], values["required_capability"],
                    _json(values.get("candidate_ids", [])),
                    _json(values.get("aggregate_version_ids", [])), values["priority"],
                    values["scientific_impact_score"], values["consensus_required"],
                    values.get("batch_key"), values.get("display_policy"),
                    bool(values.get("embargoed", False)), _json(values.get("metadata", {})),
                    values["state"], values.get("assigned_to"),
                    values.get("reservation_expires_at"), values.get("authoritative_decision"),
                    values.get("created_at", _now()), values.get("updated_at", _now()),
                ),
            )
            stored = _row(cursor, cursor.fetchone())
            assert stored is not None
            return stored

    def list_tasks(self) -> list[dict[str, Any]]:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute("SELECT * FROM oc_review.review_task ORDER BY task_id")
            return [item for row in cursor.fetchall() if (item := _row(cursor, row)) is not None]

    def append_event(self, task_id: str, event_type: str, details: dict[str, Any]) -> None:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                "INSERT INTO oc_review.review_event (task_id,event_type,details) VALUES (%s,%s,%s::jsonb)",
                (task_id, event_type, _json(details)),
            )

    def history(self, task_id: str) -> list[dict[str, Any]]:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                "SELECT * FROM oc_review.review_event WHERE task_id = %s ORDER BY event_id",
                (task_id,),
            )
            return [item for row in cursor.fetchall() if (item := _row(cursor, row)) is not None]

    def append_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                """
                INSERT INTO oc_review.review_decision
                    (task_id,decision,reviewer_id,comment,modified_value,provenance)
                VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                RETURNING *
                """,
                (
                    decision["task_id"], decision["decision"], decision["reviewer_id"],
                    decision.get("comment"), _json(decision.get("modified_value")),
                    _json(decision.get("provenance", {})),
                ),
            )
            stored = _row(cursor, cursor.fetchone())
            assert stored is not None
            return stored

    def decisions_for(self, task_id: str) -> list[dict[str, Any]]:
        with _transaction(self.connection_factory) as (_, cursor):
            cursor.execute(
                "SELECT * FROM oc_review.review_decision WHERE task_id = %s ORDER BY decision_id",
                (task_id,),
            )
            return [item for row in cursor.fetchall() if (item := _row(cursor, row)) is not None]
