from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .repositories import concept_database_url


class PostgresGlossaryRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or concept_database_url()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_concepts.glossary_candidates WHERE candidate_id=%s",
                (candidate_id,),
            )
            return cur.fetchone()

    def insert_candidate(self, row: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.glossary_candidates
                  (candidate_id, term, normalized_term, language, source_uri,
                   source_revision_id, source_checksum, evidence_span_id,
                   resolution_state, matched_concept_ids, reviewed_concept_id,
                   reviewed_by, review_rationale)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (candidate_id) DO NOTHING
                RETURNING *
                """,
                (
                    row["candidate_id"], row["term"], row["normalized_term"],
                    row["language"], row["source_uri"], row["source_revision_id"],
                    row["source_checksum"], row["evidence_span_id"],
                    row["resolution_state"], Jsonb(row["matched_concept_ids"]),
                    row.get("reviewed_concept_id"), row.get("reviewed_by"),
                    row.get("review_rationale"),
                ),
            )
            result = cur.fetchone()
            if result is not None:
                return result
            cur.execute(
                "SELECT * FROM oc_concepts.glossary_candidates WHERE candidate_id=%s",
                (row["candidate_id"],),
            )
            return cur.fetchone()

    def list_candidates(self, *, state: str | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            if state is None:
                cur.execute(
                    "SELECT * FROM oc_concepts.glossary_candidates ORDER BY created_at, candidate_id LIMIT %s",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT * FROM oc_concepts.glossary_candidates WHERE resolution_state=%s ORDER BY created_at, candidate_id LIMIT %s",
                    (state, limit),
                )
            return list(cur.fetchall())

    def review_candidate(self, candidate_id: str, updates: Mapping[str, Any]) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE oc_concepts.glossary_candidates
                SET resolution_state=%s, reviewed_concept_id=%s, reviewed_by=%s,
                    review_rationale=%s, reviewed_at=NOW(), revised_at=NOW()
                WHERE candidate_id=%s
                RETURNING *
                """,
                (
                    updates["resolution_state"], updates.get("reviewed_concept_id"),
                    updates["reviewed_by"], updates["review_rationale"], candidate_id,
                ),
            )
            return cur.fetchone()

    def get_figure_request(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_concepts.glossary_figure_requests WHERE request_id=%s",
                (request_id,),
            )
            return cur.fetchone()

    def insert_figure_request(self, row: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.glossary_figure_requests
                  (request_id, concept_id, request_type, audience, purpose,
                   source_candidate_id, review_state)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (request_id) DO NOTHING
                RETURNING *
                """,
                (
                    row["request_id"], row["concept_id"], row["request_type"],
                    row["audience"], row["purpose"], row.get("source_candidate_id"),
                    row["review_state"],
                ),
            )
            result = cur.fetchone()
            if result is not None:
                return result
            cur.execute(
                "SELECT * FROM oc_concepts.glossary_figure_requests WHERE request_id=%s",
                (row["request_id"],),
            )
            return cur.fetchone()

    def list_figure_requests(self, *, concept_id: UUID | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            if concept_id is None:
                cur.execute(
                    "SELECT * FROM oc_concepts.glossary_figure_requests ORDER BY created_at, request_id LIMIT %s",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT * FROM oc_concepts.glossary_figure_requests WHERE concept_id=%s ORDER BY created_at, request_id LIMIT %s",
                    (concept_id, limit),
                )
            return list(cur.fetchall())
