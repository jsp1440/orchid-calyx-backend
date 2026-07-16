import os
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for knowledge intake")
    return value


def create_source(*, source_type: str, title: str, content: str, content_hash: str, source_url: str | None, imported_by: str | None, extraction: Any) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_intake.sources
                    (source_type, title, source_url, raw_content, content_hash, imported_by, status, parser_version)
                VALUES (%s, %s, %s, %s, %s, %s, 'REVIEW', %s)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING id, source_type, title, source_url, content_hash, status, imported_at, parser_version
                """,
                (source_type, title, source_url, content, content_hash, imported_by, extraction.parser_version),
            )
            source = cur.fetchone()
            if source is None:
                cur.execute(
                    """
                    SELECT id, source_type, title, source_url, content_hash, status, imported_at, parser_version
                    FROM oc_intake.sources
                    WHERE content_hash = %s
                    """,
                    (content_hash,),
                )
                existing = cur.fetchone()
                if existing is None:
                    raise RuntimeError("Duplicate intake source could not be re-read after conflict")
                return {**existing, "duplicate": True}

            for entity in extraction.entities:
                cur.execute(
                    """
                    INSERT INTO oc_intake.entities
                        (source_id, entity_type, canonical_name, normalized_name, confidence, exact_text, proposed_node_json, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'DRAFT')
                    ON CONFLICT (source_id, entity_type, normalized_name) DO NOTHING
                    """,
                    (source["id"], entity.entity_type, entity.canonical_name, entity.normalized_name, entity.confidence, entity.exact_text, Jsonb(entity.metadata)),
                )
            for relation in extraction.relationships:
                cur.execute(
                    """INSERT INTO oc_intake.relationships
                    (source_id, subject_name, predicate, object_name, confidence, evidence_text, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'DRAFT')""",
                    (source["id"], relation.subject_name, relation.predicate, relation.object_name, relation.confidence, relation.evidence_text),
                )
            for task in extraction.tasks:
                cur.execute(
                    """INSERT INTO oc_intake.tasks
                    (source_id, task_type, title, priority, rationale, status)
                    VALUES (%s, %s, %s, %s, %s, 'OPEN')""",
                    (source["id"], task.task_type, task.title, task.priority, task.rationale),
                )
            cur.execute(
                """
                INSERT INTO oc_intake.review_queue (source_id, review_status)
                VALUES (%s, 'PENDING')
                ON CONFLICT (source_id) DO NOTHING
                """,
                (source["id"],),
            )
            source["duplicate"] = False
            source["entity_count"] = len(extraction.entities)
            source["relationship_count"] = len(extraction.relationships)
            source["task_count"] = len(extraction.tasks)
            return source


def list_review(limit: int = 100) -> list[dict[str, Any]]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT s.id, s.title, s.source_type, s.source_url, s.status, s.imported_at,
                count(DISTINCT e.id) AS entity_count, count(DISTINCT t.id) AS task_count
                FROM oc_intake.sources s
                LEFT JOIN oc_intake.entities e ON e.source_id = s.id
                LEFT JOIN oc_intake.tasks t ON t.source_id = s.id
                WHERE s.status IN ('REVIEW', 'APPROVED')
                GROUP BY s.id ORDER BY s.imported_at DESC LIMIT %s""",
                (limit,),
            )
            return list(cur.fetchall())


def get_source(source_id: int) -> dict[str, Any] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_intake.sources WHERE id = %s", (source_id,))
            source = cur.fetchone()
            if not source:
                return None
            for key, table in (("entities", "entities"), ("relationships", "relationships"), ("tasks", "tasks")):
                cur.execute(f"SELECT * FROM oc_intake.{table} WHERE source_id = %s ORDER BY id", (source_id,))
                source[key] = list(cur.fetchall())
            return source


def decide(source_id: int, status: str, notes: str | None) -> dict[str, Any] | None:
    review_status = "APPROVED" if status == "APPROVED" else "REJECTED"
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE oc_intake.sources SET status=%s, reviewed_at=NOW() WHERE id=%s RETURNING id, status", (status, source_id))
            result = cur.fetchone()
            if not result:
                return None
            cur.execute("UPDATE oc_intake.review_queue SET review_status=%s, review_notes=%s, reviewed_at=NOW() WHERE source_id=%s", (review_status, notes, source_id))
            return result


def mark_published(source_id: int) -> dict[str, Any] | None:
    # BUILD-070 deliberately records publication approval only. Graph mutation is reserved
    # for a later adapter with explicit canonical mappings and an independent safety review.
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE oc_intake.sources SET status='PUBLISHED', published_at=NOW() WHERE id=%s AND status='APPROVED' RETURNING id, status, published_at", (source_id,))
            result = cur.fetchone()
            if result:
                cur.execute("UPDATE oc_intake.review_queue SET review_status='PUBLISHED', published_at=NOW() WHERE source_id=%s", (source_id,))
            return result
