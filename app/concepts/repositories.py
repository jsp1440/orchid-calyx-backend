import json
import os
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def concept_database_url() -> str:
    value = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for concept registry operations")
    return value


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


class PostgresConceptRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or concept_database_url()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _audit(cur, actor: str, action: str, concept_id: UUID, resulting: Any) -> None:
        cur.execute(
            """
            INSERT INTO oc_concepts.concept_audit_events
              (actor, action, concept_id, resulting_state)
            VALUES (%s, %s, %s, %s)
            """,
            (actor, action, concept_id, Jsonb(_json_safe(resulting))),
        )

    def create_scheme(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.concept_schemes
                  (scheme_id, scheme_key, name, authority, steward, review_state)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data["scheme_id"],
                    data["scheme_key"],
                    data["name"],
                    data["authority"],
                    data["steward"],
                    data["review_state"],
                ),
            )
            return cur.fetchone()

    def get_scheme(self, scheme_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_concepts.concept_schemes WHERE scheme_id=%s",
                (scheme_id,),
            )
            return cur.fetchone()

    def create_release(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.concept_releases
                  (release_id, scheme_id, version, status, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data["release_id"],
                    data["scheme_id"],
                    data["version"],
                    data["status"],
                    Jsonb(data["metadata"]),
                ),
            )
            return cur.fetchone()

    def get_release(self, release_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_concepts.concept_releases WHERE release_id=%s",
                (release_id,),
            )
            return cur.fetchone()

    def create_concept(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.concepts
                  (concept_id, concept_uri, scheme_id, release_id, status,
                   review_state, steward)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data["concept_id"],
                    data["concept_uri"],
                    data["scheme_id"],
                    data.get("release_id"),
                    data["status"],
                    data["review_state"],
                    data["steward"],
                ),
            )
            result = cur.fetchone()
            self._audit(
                cur, data["steward"], "CONCEPT_CREATED", result["concept_id"], result
            )
            return result

    def get_concept(self, identifier: UUID | str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.*, s.scheme_key, s.name AS scheme_name,
                       r.version AS release_version, r.metadata AS release_metadata
                FROM oc_concepts.concepts c
                JOIN oc_concepts.concept_schemes s ON s.scheme_id=c.scheme_id
                LEFT JOIN oc_concepts.concept_releases r ON r.release_id=c.release_id
                WHERE c.concept_id=%s
                """,
                (identifier,),
            )
            return cur.fetchone()

    def transition_concept(
        self,
        concept_id: UUID,
        status: str,
        review_state: str,
        superseded_by_id: UUID | None,
        actor: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE oc_concepts.concepts
                SET status=%s, review_state=%s, superseded_by_id=%s,
                    revised_at=NOW()
                WHERE concept_id=%s
                RETURNING *
                """,
                (status, review_state, superseded_by_id, concept_id),
            )
            result = cur.fetchone()
            if result is not None:
                self._audit(cur, actor, f"CONCEPT_{status}", concept_id, result)
            return result

    def adapt_ontology_term(
        self,
        term_id: int,
        concept_data: Mapping[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.*
                FROM oc_concepts.ontology_term_concepts m
                JOIN oc_concepts.concepts c ON c.concept_id=m.concept_id
                WHERE m.ontology_term_id=%s
                """,
                (term_id,),
            )
            existing = cur.fetchone()
            if existing is not None:
                return existing
            cur.execute(
                "SELECT id FROM oc_ontology.ontology_terms WHERE id=%s",
                (term_id,),
            )
            if cur.fetchone() is None:
                raise LookupError("ONTOLOGY_TERM_NOT_FOUND")
            cur.execute(
                """
                INSERT INTO oc_concepts.concepts
                  (concept_id, concept_uri, scheme_id, release_id, status,
                   review_state, steward)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    concept_data["concept_id"],
                    concept_data["concept_uri"],
                    concept_data["scheme_id"],
                    concept_data.get("release_id"),
                    concept_data["status"],
                    concept_data["review_state"],
                    concept_data["steward"],
                ),
            )
            result = cur.fetchone()
            cur.execute(
                """
                INSERT INTO oc_concepts.ontology_term_concepts
                  (ontology_term_id, concept_id, adapted_by)
                VALUES (%s, %s, %s)
                """,
                (term_id, result["concept_id"], actor),
            )
            self._audit(
                cur, actor, "ONTOLOGY_TERM_ADAPTED", result["concept_id"], result
            )
            return result

    def create_label(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.concept_labels
                  (label_id, concept_id, label_type, label, normalized_label,
                   language, script, editorial_context, provenance, review_state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data["label_id"], data["concept_id"], data["label_type"],
                    data["label"], data["normalized_label"], data["language"],
                    data.get("script"), data["editorial_context"],
                    Jsonb(data["provenance"]), data["review_state"],
                ),
            )
            result = cur.fetchone()
            self._audit(cur, data["actor"], "CONCEPT_LABEL_CREATED", data["concept_id"], result)
            return result

    def list_labels(self, concept_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM oc_concepts.concept_labels
                WHERE concept_id=%s
                ORDER BY language, editorial_context,
                  CASE label_type WHEN 'PREFERRED' THEN 0 ELSE 1 END,
                  normalized_label, label_id
                """,
                (concept_id,),
            )
            return list(cur.fetchall())

    def search_labels(
        self,
        normalized_query: str,
        *,
        language: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.*, c.concept_uri, c.status AS concept_status,
                       c.review_state AS concept_review_state,
                       CASE
                         WHEN l.normalized_label=%s THEN 0
                         WHEN l.normalized_label LIKE %s THEN 1
                         ELSE 2
                       END AS match_rank
                FROM oc_concepts.concept_labels l
                JOIN oc_concepts.concepts c ON c.concept_id=l.concept_id
                WHERE (%s IS NULL OR l.language=%s)
                  AND (l.normalized_label=%s OR l.normalized_label LIKE %s)
                ORDER BY match_rank,
                  CASE l.label_type WHEN 'PREFERRED' THEN 0 ELSE 1 END,
                  l.normalized_label, l.concept_id, l.label_id
                LIMIT %s
                """,
                (
                    normalized_query,
                    f"{normalized_query}%",
                    language,
                    language,
                    normalized_query,
                    f"{normalized_query}%",
                    limit,
                ),
            )
            return list(cur.fetchall())

    def create_definition(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_concepts.concept_definitions
                  (definition_id, concept_id, definition_type, text, language,
                   script, provenance, review_state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data["definition_id"], data["concept_id"],
                    data["definition_type"], data["text"], data["language"],
                    data.get("script"), Jsonb(data["provenance"]),
                    data["review_state"],
                ),
            )
            result = cur.fetchone()
            self._audit(cur, data["actor"], "CONCEPT_DEFINITION_CREATED", data["concept_id"], result)
            return result

    def list_definitions(self, concept_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM oc_concepts.concept_definitions
                WHERE concept_id=%s
                ORDER BY language, definition_type, definition_id
                """,
                (concept_id,),
            )
            return list(cur.fetchall())
