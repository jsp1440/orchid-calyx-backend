from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.archive.registry import ArchiveRegistry


class SemanticIndexer(Protocol):
    def index_document(
        self, document_id: str, text: str, metadata: dict[str, Any]
    ) -> None: ...


class KnowledgeGraphExporter(Protocol):
    def export_entities_and_relationships(
        self, document_id: str
    ) -> dict[str, Any]: ...


class ArchiveSearch:
    def __init__(self, registry: ArchiveRegistry | None = None) -> None:
        self.registry = registry or ArchiveRegistry()

    def documents(
        self, *, query: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        sql = "SELECT id,canonical_title,metadata,created_at,updated_at FROM archive_documents"
        params: list[Any] = []
        if query:
            sql += " WHERE canonical_title ILIKE %s OR extracted_text ILIKE %s"
            pattern = f"%{query}%"
            params.extend((pattern, pattern))
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        with self.registry.connection() as conn:
            return list(conn.execute(sql, params).fetchall())

    def document(self, document_id: UUID) -> dict[str, Any] | None:
        with self.registry.connection() as conn:
            document = conn.execute(
                "SELECT * FROM archive_documents WHERE id=%s", (document_id,)
            ).fetchone()
            if not document:
                return None
            files = list(
                conn.execute(
                    "SELECT * FROM archive_files WHERE document_id=%s ORDER BY created_at",
                    (document_id,),
                ).fetchall()
            )
            entities = list(
                conn.execute(
                    "SELECT * FROM archive_entities WHERE document_id=%s ORDER BY created_at",
                    (document_id,),
                ).fetchall()
            )
            relationships = list(
                conn.execute(
                    "SELECT * FROM archive_relationships WHERE document_id=%s ORDER BY created_at",
                    (document_id,),
                ).fetchall()
            )
        return {
            "document": document,
            "files": files,
            "entities": entities,
            "relationships": relationships,
        }

    def entities(
        self,
        *,
        query: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            clauses.append("label ILIKE %s")
            params.append(f"%{query}%")
        if entity_type:
            clauses.append("entity_type=%s")
            params.append(entity_type)
        sql = "SELECT * FROM archive_entities"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        with self.registry.connection() as conn:
            return list(conn.execute(sql, params).fetchall())

    def runs(
        self, *, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM archive_import_runs"
        params: list[Any] = []
        if status:
            sql += " WHERE status=%s"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        with self.registry.connection() as conn:
            return list(conn.execute(sql, params).fetchall())
