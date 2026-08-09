from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .repositories import concept_database_url


def _decision_digest(candidate_id: str, updates: Mapping[str, Any]) -> str:
    payload = {
        "candidate_id": candidate_id,
        "resolution_state": updates["resolution_state"],
        "reviewed_concept_id": str(updates.get("reviewed_concept_id") or ""),
        "reviewed_by": updates["reviewed_by"],
        "review_rationale": updates["review_rationale"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PostgresGlossaryRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or concept_database_url()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_concepts.glossary_candidates WHERE candidate_id=%s", (candidate_id,))
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
                    row["candidate_id"], row["term"], row["normalized_term"], row["language"],
                    row["source_uri"], row["source_revision_id"], row["source_checksum"],
                    row["evidence_span_id"], row["resolution_state"], Jsonb(row["matched_concept_ids"]),
                    row.get("reviewed_concept_id"), row.get("reviewed_by"), row.get("review_rationale"),
                ),
            )
            result = cur.fetchone()
            if result is not None:
                return result
            cur.execute("SELECT * FROM oc_concepts.glossary_candidates WHERE candidate_id=%s", (row["candidate_id"],))
            existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("GLOSSARY_CANDIDATE_UPSERT_FAILED")
            return existing

    def list_candidates(self, *, state: str | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            if state is None:
                cur.execute("SELECT * FROM oc_concepts.glossary_candidates ORDER BY created_at, candidate_id LIMIT %s", (limit,))
            else:
                cur.execute(
                    "SELECT * FROM oc_concepts.glossary_candidates WHERE resolution_state=%s ORDER BY created_at, candidate_id LIMIT %s",
                    (state, limit),
                )
            return list(cur.fetchall())

    def review_candidate(self, candidate_id: str, updates: Mapping[str, Any]) -> dict[str, Any] | None:
        decision_digest = _decision_digest(candidate_id, updates)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE oc_concepts.glossary_candidates
                SET resolution_state=%s, reviewed_concept_id=%s, reviewed_by=%s,
                    review_rationale=%s, reviewed_at=NOW(), revised_at=NOW()
                WHERE candidate_id=%s
                  AND resolution_state NOT IN ('REVIEWED_MATCH','NEW_CONCEPT_CANDIDATE','REJECTED')
                RETURNING *
                """,
                (updates["resolution_state"], updates.get("reviewed_concept_id"), updates["reviewed_by"], updates["review_rationale"], candidate_id),
            )
            result = cur.fetchone()
            if result is None:
                cur.execute("SELECT * FROM oc_concepts.glossary_candidates WHERE candidate_id=%s", (candidate_id,))
                existing = cur.fetchone()
                if existing is None:
                    return None
                existing_digest = _decision_digest(
                    candidate_id,
                    {
                        "resolution_state": existing["resolution_state"],
                        "reviewed_concept_id": existing.get("reviewed_concept_id"),
                        "reviewed_by": existing.get("reviewed_by"),
                        "review_rationale": existing.get("review_rationale"),
                    },
                )
                if existing_digest == decision_digest:
                    return existing
                raise ValueError("GLOSSARY_REVIEW_DECISION_IMMUTABLE")
            cur.execute(
                """
                INSERT INTO oc_concepts.glossary_candidate_review_events
                  (decision_digest, candidate_id, resolution_state, reviewed_concept_id, reviewed_by, review_rationale)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (decision_digest) DO NOTHING
                """,
                (decision_digest, candidate_id, updates["resolution_state"], updates.get("reviewed_concept_id"), updates["reviewed_by"], updates["review_rationale"]),
            )
            return result

    def get_figure_request(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_concepts.glossary_figure_requests WHERE request_id=%s", (request_id,))
            return cur.fetchone()

    def insert_figure_request(self, row: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.glossary_figure_requests
                  (request_id, concept_id, request_type, audience, purpose, source_candidate_id,
                   subject_label, scientific_context_status, suggested_title, suggested_caption,
                   provider_prompt, review_state, review_required)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (request_id) DO NOTHING
                RETURNING *
                """,
                (
                    row["request_id"], row.get("concept_id"), row["request_type"], row["audience"], row["purpose"],
                    row.get("source_candidate_id"), row["subject_label"], row["scientific_context_status"],
                    row["suggested_title"], row["suggested_caption"], row["provider_prompt"],
                    row["review_state"], row["review_required"],
                ),
            )
            result = cur.fetchone()
            if result is not None:
                return result
            cur.execute("SELECT * FROM oc_concepts.glossary_figure_requests WHERE request_id=%s", (row["request_id"],))
            existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("GLOSSARY_FIGURE_REQUEST_UPSERT_FAILED")
            return existing

    def list_figure_requests(
        self,
        *,
        concept_id: UUID | None,
        source_candidate_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if concept_id is not None:
            clauses.append("concept_id=%s")
            params.append(concept_id)
        if source_candidate_id is not None:
            clauses.append("source_candidate_id=%s")
            params.append(source_candidate_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        query = f"SELECT * FROM oc_concepts.glossary_figure_requests {where} ORDER BY created_at, request_id LIMIT %s"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return list(cur.fetchall())
