from __future__ import annotations

from typing import Any, Protocol

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
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self.registry.connection() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM archive_documents ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                ).fetchall()
            )

    def entities(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self.registry.connection() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM archive_entities ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                ).fetchall()
            )
