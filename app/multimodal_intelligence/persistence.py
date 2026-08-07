from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .operator import MultimodalError, OperationRecord, ReviewDecision


class PostgresOperationRepository:
    """Postgres implementation of OperationRepository.

    Construction is inert. Callers must explicitly provide a connection factory;
    this module never reads credentials, opens a connection at import time, or
    applies migrations automatically.
    """

    def __init__(self, connection_factory: Callable[[], psycopg.Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    @staticmethod
    def _record(row: tuple[Any, ...]) -> OperationRecord:
        review_data = row[8]
        review = ReviewDecision(**review_data) if review_data else None
        return OperationRecord(
            operation_id=str(row[0]),
            operation_type=row[1],
            request_hash=row[2],
            state=row[3],
            result=row[4],
            created_at=row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
            provenance=row[6],
            human_review_required=bool(row[7]),
            review=review,
            errors=tuple(row[9] or ()),
        )

    def get_by_hash(self, request_hash: str) -> OperationRecord | None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_id, operation_type, request_hash, state, result,
                       created_at, provenance, human_review_required, review, errors
                FROM calyx_multimodal_operations
                WHERE request_hash = %s
                """,
                (request_hash,),
            )
            row = cursor.fetchone()
        return self._record(row) if row else None

    def get(self, operation_id: str) -> OperationRecord | None:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_id, operation_type, request_hash, state, result,
                       created_at, provenance, human_review_required, review, errors
                FROM calyx_multimodal_operations
                WHERE operation_id = %s
                """,
                (operation_id,),
            )
            row = cursor.fetchone()
        return self._record(row) if row else None

    def save(self, record: OperationRecord) -> OperationRecord:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO calyx_multimodal_operations (
                    operation_id, operation_type, request_hash, state, result,
                    created_at, provenance, human_review_required, review, errors
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_hash) DO NOTHING
                RETURNING operation_id
                """,
                (
                    record.operation_id,
                    record.operation_type,
                    record.request_hash,
                    record.state,
                    Jsonb(record.result),
                    record.created_at,
                    Jsonb(record.provenance),
                    record.human_review_required,
                    Jsonb(asdict(record.review)) if record.review else None,
                    Jsonb(list(record.errors)),
                ),
            )
            inserted = cursor.fetchone()
            connection.commit()
        if inserted:
            return record
        existing = self.get_by_hash(record.request_hash)
        if existing is None:
            raise MultimodalError("PERSISTENCE_CONFLICT", "Idempotent operation could not be reloaded.")
        return existing

    def replace(self, record: OperationRecord) -> OperationRecord:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE calyx_multimodal_operations
                SET state = %s,
                    result = %s,
                    provenance = %s,
                    human_review_required = %s,
                    review = %s,
                    errors = %s
                WHERE operation_id = %s
                """,
                (
                    record.state,
                    Jsonb(record.result),
                    Jsonb(record.provenance),
                    record.human_review_required,
                    Jsonb(asdict(record.review)) if record.review else None,
                    Jsonb(list(record.errors)),
                    record.operation_id,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise MultimodalError("OPERATION_NOT_FOUND", "Operation does not exist.")
            connection.commit()
        return record

    def list_records(self) -> tuple[OperationRecord, ...]:
        with self._connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_id, operation_type, request_hash, state, result,
                       created_at, provenance, human_review_required, review, errors
                FROM calyx_multimodal_operations
                ORDER BY created_at, operation_id
                """
            )
            rows = cursor.fetchall()
        return tuple(self._record(row) for row in rows)
