"""Durable record storage for Research Station projects.

Research Station wrote its authoritative state as JSON under
``CALYX_RESEARCH_STATION_DIR``, defaulting to ``/tmp/calyx/research-station``.
On any container that recycles ``/tmp`` — which is what ``/tmp`` is for — a
project, its questions, its claims and its evidence are gone at the next
restart, and nothing reports that they were lost. A research workspace whose
contents evaporate is not a workspace; it is a cache that looks like one.

This module makes the database authoritative and leaves the filesystem as the
cache it always was. It deliberately adds no new database subsystem: one table
of JSON records, reached through the same ``db_execute`` callable the rest of
the admin surface already uses.

Records are keyed by ``(owner_key, project_id, kind, record_id)``, so a project
bound to a BUILD-051 research request keeps that request's identity as its
project id and everything belonging to it is reachable from that one key after
a restart.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

TABLE = "oc_admin.research_station_records"

#: Record kinds whose authoritative copy must survive a restart. The list is
#: explicit rather than "everything written" so that adding a genuinely
#: ephemeral cache file later is a deliberate decision, not an accident.
DURABLE_KINDS = frozenset(
    {
        "project",
        "question",
        "protocol",
        "dataset",
        "attachment",
        "claim",
        "evidence",
        "decision",
        "notebook",
        "artifact",
        "task",
    }
)


class ProjectRecordStore(Protocol):
    def put(
        self, *, owner_key: str, project_id: str, kind: str, record_id: str, record: Mapping[str, Any]
    ) -> None: ...

    def get(
        self, *, owner_key: str, project_id: str, kind: str, record_id: str
    ) -> dict[str, Any] | None: ...

    def list(self, *, owner_key: str, project_id: str, kind: str) -> list[dict[str, Any]]: ...


class MemoryProjectRecordStore:
    """In-process store for tests and for a machine with no database.

    Not durable, and it does not pretend to be: :func:`persistence_mode`
    reports which store is live so no caller has to assume.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def put(self, *, owner_key, project_id, kind, record_id, record) -> None:
        self._records[(owner_key, project_id, kind, record_id)] = dict(record)

    def get(self, *, owner_key, project_id, kind, record_id):
        found = self._records.get((owner_key, project_id, kind, record_id))
        return dict(found) if found is not None else None

    def list(self, *, owner_key, project_id, kind):
        return [
            dict(value)
            for (owner, project, record_kind, _), value in sorted(self._records.items())
            if owner == owner_key and project == project_id and record_kind == kind
        ]


class PostgresProjectRecordStore:
    """Canonical store over ``oc_admin.research_station_records``."""

    def __init__(self, db_execute: Callable[[Callable[[Any], Any]], Any]) -> None:
        self._db_execute = db_execute

    def put(self, *, owner_key, project_id, kind, record_id, record) -> None:
        def _work(cur):
            if cur is None:
                return None
            from psycopg.types.json import Jsonb

            cur.execute(
                f"""
                INSERT INTO {TABLE}
                    (owner_key, project_id, kind, record_id, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (owner_key, project_id, kind, record_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                (owner_key, project_id, kind, record_id, Jsonb(dict(record))),
            )
            return None

        self._db_execute(_work)

    def get(self, *, owner_key, project_id, kind, record_id):
        def _work(cur):
            if cur is None:
                return None
            cur.execute(
                f"""
                SELECT payload FROM {TABLE}
                WHERE owner_key = %s AND project_id = %s AND kind = %s AND record_id = %s
                """,
                (owner_key, project_id, kind, record_id),
            )
            row = cur.fetchone()
            return dict(row["payload"]) if row else None

        return self._db_execute(_work)

    def list(self, *, owner_key, project_id, kind):
        def _work(cur):
            if cur is None:
                return []
            cur.execute(
                f"""
                SELECT payload FROM {TABLE}
                WHERE owner_key = %s AND project_id = %s AND kind = %s
                ORDER BY record_id ASC
                """,
                (owner_key, project_id, kind),
            )
            return [dict(row["payload"]) for row in cur.fetchall()]

        return self._db_execute(_work) or []


def persistence_mode(env: Mapping[str, str] | None = None) -> str:
    """``durable_database`` or ``in_process_memory`` — stated, never assumed."""
    import os

    source = env if env is not None else os.environ
    return (
        "durable_database"
        if str(source.get("DATABASE_URL", "")).strip()
        else "in_process_memory"
    )


def build_record_store(
    *,
    env: Mapping[str, str] | None = None,
    db_execute: Callable[[Callable[[Any], Any]], Any] | None = None,
) -> ProjectRecordStore:
    if persistence_mode(env) == "durable_database":
        if db_execute is None:
            from app.routers.owner_operations import db_execute as _db_execute

            db_execute = _db_execute
        return PostgresProjectRecordStore(db_execute)
    return MemoryProjectRecordStore()
