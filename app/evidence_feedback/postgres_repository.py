"""PostgreSQL store for evidence feedback with the file store's exact contract.

Selected automatically when the backend has a configured database (see
``routes._repository``). Semantics are identical to
``FileEvidenceFeedbackRepository``: exact-version registration (re-registering
the same displayed content returns the original record unchanged), immutable
versions with lineage checks, fingerprint duplicate detection with
``FINGERPRINT_ALREADY_BOUND``, and append-only case events.

Records are stored as the same canonical JSON text the file store writes, so a
record read back is byte-for-byte what was written and the content hash of a
payload never changes on a round trip.

The module owns its tables in the ``oc_evidence_feedback`` schema and creates
them with additive, idempotent DDL only when they are absent (the pattern of
``app.persistence.state_repository``). An index added later
(``ADDITIVE_INDEXES``) is created on an existing database when missing. It
never drops, rewrites or migrates existing tables. A database that already has the tables (for example
pre-provisioned by the owner with ``SCHEMA_STATEMENTS``) needs no DDL
privilege at runtime.

Every database failure surfaces as ``EvidenceFeedbackStoreUnavailable`` so the
HTTP layer answers 503 instead of falling back to files and splitting data.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row

from .models import EvidenceFeedbackCase, EvidenceObjectVersion, canonical_json
from .repository import (
    EvidenceFeedbackRepositoryError,
    EvidenceFeedbackStoreUnavailable,
    is_same_version,
    normalized_key,
    normalized_version_hash,
    payload_version_hash,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)

SCHEMA = "oc_evidence_feedback"
TABLES = ("object_versions", "cases", "case_fingerprints", "case_events")
# First key of the two-integer advisory locks; distinct from the BUILD-086
# runtime snapshot locks (8601, 8602).
LOCK_NAMESPACE = 8612
BOOTSTRAP_LOCK_KEY = "schema-bootstrap"

# Owner review queue order (see ``repository.review_order_key``): the case's
# ``created_at`` then its key, compared by code point so both stores agree.
CASE_CREATED_AT_SQL = "(((record_json::jsonb)->>'created_at') COLLATE \"C\")"
CASE_KEY_ORDER_SQL = '(case_key COLLATE "C")'
CASE_OBJECT_TYPE_SQL = "((record_json::jsonb)->>'object_type')"

# Indexes added after the tables first shipped. ``ensure_schema`` creates any
# that are missing on an existing database (additively, best effort).
ADDITIVE_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "cases_review_order_idx",
        (
            "CREATE INDEX IF NOT EXISTS cases_review_order_idx "
            f"ON {SCHEMA}.cases({CASE_CREATED_AT_SQL} DESC, {CASE_KEY_ORDER_SQL} DESC)"
        ),
    ),
)

# Additive and idempotent. Nothing here drops, truncates, or alters an
# existing object; an owner can run these statements verbatim to pre-provision.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}",
    f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA}.object_versions(
        object_key TEXT NOT NULL CHECK (object_key <> ''),
        version_hash TEXT NOT NULL CHECK (version_hash ~ '^[0-9a-f]{{64}}$'),
        object_type TEXT NOT NULL,
        previous_version_hash TEXT,
        record_json TEXT NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (object_key, version_hash)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA}.cases(
        case_key TEXT PRIMARY KEY CHECK (case_key <> ''),
        fingerprint TEXT NOT NULL,
        object_key TEXT NOT NULL,
        object_version_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        disposition TEXT NOT NULL,
        record_json TEXT NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA}.case_fingerprints(
        fingerprint_key TEXT PRIMARY KEY CHECK (fingerprint_key <> ''),
        case_key TEXT NOT NULL REFERENCES {SCHEMA}.cases(case_key),
        bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA}.case_events(
        event_id BIGSERIAL PRIMARY KEY,
        case_key TEXT NOT NULL REFERENCES {SCHEMA}.cases(case_key),
        record_json TEXT NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS case_events_case_idx "
        f"ON {SCHEMA}.case_events(case_key, event_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS cases_status_idx "
        f"ON {SCHEMA}.cases(status, updated_at)"
    ),
    *(statement for _, statement in ADDITIVE_INDEXES),
)


class PostgresEvidenceFeedbackRepository:
    """Durable evidence-feedback store backed by the configured database."""

    def __init__(self, database_url: str, *, connect_timeout: int = 10) -> None:
        if not database_url:
            raise EvidenceFeedbackStoreUnavailable()
        self.database_url = database_url
        self.connect_timeout = connect_timeout
        self._local = threading.local()
        self.ensure_schema()

    # -- connection and transaction handling ---------------------------------

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=self.connect_timeout,
        )

    @staticmethod
    def _lock(cur: psycopg.Cursor, lock_key: str) -> None:
        cur.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (LOCK_NAMESPACE, lock_key),
        )

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor]:
        active = getattr(self._local, "connection", None)
        if active is not None:
            with active.cursor() as cur:
                yield cur
            return
        try:
            with self._connect() as conn, conn.cursor() as cur:
                yield cur
        except psycopg.Error as exc:
            raise EvidenceFeedbackStoreUnavailable() from exc

    def atomic(
        self, operation: Callable[[], T], *, lock_key: str | None = None
    ) -> T:
        """Run ``operation`` in one transaction, serialized on ``lock_key``.

        Nested calls join the outer transaction. Any exception rolls the whole
        transaction back, so a case is never stored without its audit event.
        """

        active = getattr(self._local, "connection", None)
        if active is not None:
            if lock_key:
                with active.cursor() as cur:
                    self._lock(cur, lock_key)
            return operation()
        try:
            with self._connect() as conn:
                self._local.connection = conn
                try:
                    if lock_key:
                        with conn.cursor() as cur:
                            self._lock(cur, lock_key)
                    return operation()
                finally:
                    self._local.connection = None
        except psycopg.Error as exc:
            raise EvidenceFeedbackStoreUnavailable() from exc

    def ensure_schema(self) -> None:
        """Create the owned tables when absent; never alter existing ones."""

        try:
            with self._connect() as conn, conn.cursor() as cur:
                if self._tables_present(cur):
                    self._ensure_additive_indexes(conn, cur)
                    return
                self._lock(cur, BOOTSTRAP_LOCK_KEY)
                if self._tables_present(cur):
                    self._ensure_additive_indexes(conn, cur)
                    return
                for statement in SCHEMA_STATEMENTS:
                    cur.execute(statement)
        except psycopg.Error as exc:
            raise EvidenceFeedbackStoreUnavailable() from exc

    def _ensure_additive_indexes(
        self, conn: psycopg.Connection, cur: psycopg.Cursor
    ) -> None:
        """Create any missing later-added index; never alter anything else.

        Indexes only speed up queries, so a role without DDL privilege on
        owner-provisioned tables keeps working (unindexed) with a warning.
        """

        for name, statement in ADDITIVE_INDEXES:
            cur.execute("SELECT to_regclass(%s) AS relation", (f"{SCHEMA}.{name}",))
            row = cur.fetchone()
            if row and row.get("relation"):
                continue
            try:
                with conn.transaction():
                    self._lock(cur, BOOTSTRAP_LOCK_KEY)
                    cur.execute(statement)
            except psycopg.errors.InsufficientPrivilege:
                logger.warning(
                    "Evidence feedback index %s.%s is missing and this role "
                    "cannot create it; review listing still works unindexed.",
                    SCHEMA,
                    name,
                )

    @staticmethod
    def _tables_present(cur: psycopg.Cursor) -> bool:
        for table in TABLES:
            cur.execute("SELECT to_regclass(%s) AS relation", (f"{SCHEMA}.{table}",))
            row = cur.fetchone()
            if not row or not row.get("relation"):
                return False
        return True

    # -- cases -----------------------------------------------------------------

    def save_case(self, case: EvidenceFeedbackCase) -> None:
        fingerprint_key = normalized_key(case.fingerprint, code="FINGERPRINT_REQUIRED")

        def operation() -> None:
            existing = self.find_by_fingerprint(case.fingerprint)
            if existing is not None and existing.case_id != case.case_id:
                raise EvidenceFeedbackRepositoryError("FINGERPRINT_ALREADY_BOUND")
            case_key = normalized_key(case.case_id, code="CASE_ID_REQUIRED")
            with self._cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.cases(
                        case_key, fingerprint, object_key, object_version_hash,
                        status, disposition, record_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_key) DO UPDATE SET
                        fingerprint = EXCLUDED.fingerprint,
                        object_key = EXCLUDED.object_key,
                        object_version_hash = EXCLUDED.object_version_hash,
                        status = EXCLUDED.status,
                        disposition = EXCLUDED.disposition,
                        record_json = EXCLUDED.record_json,
                        updated_at = now()
                    """,
                    (
                        case_key,
                        case.fingerprint,
                        case.object_id.strip(),
                        case.object_version_hash,
                        case.status.value,
                        case.disposition.value,
                        canonical_json(case.to_dict()),
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.case_fingerprints(fingerprint_key, case_key)
                    VALUES (%s, %s)
                    ON CONFLICT (fingerprint_key) DO UPDATE SET case_key = EXCLUDED.case_key
                    """,
                    (fingerprint_key, case_key),
                )

        self.atomic(operation, lock_key=f"fingerprint:{fingerprint_key}")

    def _case_by_key(self, cur: psycopg.Cursor, case_key: str) -> EvidenceFeedbackCase:
        cur.execute(
            f"SELECT record_json FROM {SCHEMA}.cases WHERE case_key = %s",
            (case_key,),
        )
        row = cur.fetchone()
        if row is None:
            raise EvidenceFeedbackRepositoryError("CASE_NOT_FOUND")
        return EvidenceFeedbackCase.from_dict(json.loads(row["record_json"]))

    def get_case(self, case_id: str) -> EvidenceFeedbackCase:
        case_key = normalized_key(case_id, code="CASE_ID_REQUIRED")
        with self._cursor() as cur:
            return self._case_by_key(cur, case_key)

    def find_by_fingerprint(self, fingerprint: str) -> EvidenceFeedbackCase | None:
        fingerprint_key = normalized_key(fingerprint, code="FINGERPRINT_REQUIRED")
        with self._cursor() as cur:
            cur.execute(
                f"SELECT case_key FROM {SCHEMA}.case_fingerprints WHERE fingerprint_key = %s",
                (fingerprint_key,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._case_by_key(cur, row["case_key"])

    def append_event(
        self,
        *,
        case_id: str,
        event: str,
        timestamp: str,
        actor_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.get_case(case_id)
        record = {
            "case_id": case_id,
            "event": event,
            "timestamp": timestamp,
            "actor_id": actor_id,
            "details": details or {},
        }
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO {SCHEMA}.case_events(case_key, record_json) VALUES (%s, %s)",
                (case_id.strip(), canonical_json(record)),
            )

    def list_events(self, case_id: str) -> list[dict[str, Any]]:
        self.get_case(case_id)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT record_json FROM {SCHEMA}.case_events "
                "WHERE case_key = %s ORDER BY event_id",
                (case_id.strip(),),
            )
            return [json.loads(row["record_json"]) for row in cur.fetchall()]

    def list_cases(
        self,
        *,
        status: str | None,
        object_type: str | None,
        limit: int,
        before: tuple[str, str] | None,
    ) -> list[EvidenceFeedbackCase]:
        """Cases newest first, strictly after the ``before`` keyset cursor.

        Served by ``cases_review_order_idx`` (``cases_status_idx`` when the
        status filter is the most selective); ``limit`` bounds every read.
        """

        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if object_type is not None:
            clauses.append(f"{CASE_OBJECT_TYPE_SQL} = %s")
            params.append(object_type)
        if before is not None:
            clauses.append(
                f"({CASE_CREATED_AT_SQL} < %s OR ({CASE_CREATED_AT_SQL} = %s "
                f"AND {CASE_KEY_ORDER_SQL} < %s))"
            )
            params.extend((before[0], before[0], before[1]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(0, limit))
        with self._cursor() as cur:
            cur.execute(
                f"SELECT record_json FROM {SCHEMA}.cases {where} "
                f"ORDER BY {CASE_CREATED_AT_SQL} DESC, {CASE_KEY_ORDER_SQL} DESC "
                "LIMIT %s",
                params,
            )
            rows = cur.fetchall()
        return [
            EvidenceFeedbackCase.from_dict(json.loads(row["record_json"]))
            for row in rows
        ]

    def count_case_events(
        self, case_ids: Sequence[str], event: str
    ) -> dict[str, int]:
        keys = [case_id.strip() for case_id in case_ids]
        counts = dict.fromkeys(case_ids, 0)
        if not keys:
            return counts
        with self._cursor() as cur:
            cur.execute(
                f"SELECT case_key, count(*) AS total FROM {SCHEMA}.case_events "
                "WHERE case_key = ANY(%s) "
                "AND (record_json::jsonb)->>'event' = %s "
                "GROUP BY case_key",
                (keys, event),
            )
            totals = {row["case_key"]: int(row["total"]) for row in cur.fetchall()}
        return {case_id: totals.get(case_id.strip(), 0) for case_id in case_ids}

    # -- object versions -------------------------------------------------------

    def save_object_version(
        self, version: EvidenceObjectVersion
    ) -> EvidenceObjectVersion:
        """Persist ``version`` once and return the authoritative stored record."""

        expected = payload_version_hash(version)
        object_key = normalized_key(version.object_id, code="OBJECT_ID_REQUIRED")

        def operation() -> EvidenceObjectVersion:
            persisted = self._find_version(object_key, expected)
            if persisted is not None:
                if not is_same_version(persisted, version):
                    raise EvidenceFeedbackRepositoryError(
                        "OBJECT_VERSION_IMMUTABILITY_VIOLATION"
                    )
                return persisted
            if version.previous_version_hash is not None:
                self.get_object_version(
                    version.object_id,
                    version.previous_version_hash,
                )
            with self._cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.object_versions(
                        object_key, version_hash, object_type,
                        previous_version_hash, record_json
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        object_key,
                        expected,
                        version.object_type.value,
                        version.previous_version_hash,
                        canonical_json(version.to_dict()),
                    ),
                )
            return version

        return self.atomic(operation, lock_key=f"object:{object_key}")

    def _find_version(
        self, object_key: str, version_hash: str
    ) -> EvidenceObjectVersion | None:
        with self._cursor() as cur:
            cur.execute(
                f"SELECT record_json FROM {SCHEMA}.object_versions "
                "WHERE object_key = %s AND version_hash = %s",
                (object_key, version_hash),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return EvidenceObjectVersion.from_dict(json.loads(row["record_json"]))

    def get_object_version(
        self, object_id: str, version_hash: str
    ) -> EvidenceObjectVersion:
        normalized = normalized_version_hash(version_hash)
        object_key = normalized_key(object_id, code="OBJECT_ID_REQUIRED")
        persisted = self._find_version(object_key, normalized)
        if persisted is None:
            raise EvidenceFeedbackRepositoryError("OBJECT_VERSION_NOT_FOUND")
        return persisted

    def list_object_versions(self, object_id: str) -> list[EvidenceObjectVersion]:
        object_key = normalized_key(object_id, code="OBJECT_ID_REQUIRED")
        with self._cursor() as cur:
            cur.execute(
                f"SELECT record_json FROM {SCHEMA}.object_versions "
                "WHERE object_key = %s ORDER BY version_hash",
                (object_key,),
            )
            rows = cur.fetchall()
        return [
            EvidenceObjectVersion.from_dict(json.loads(row["record_json"]))
            for row in rows
        ]
