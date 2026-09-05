from datetime import UTC, datetime
from typing import Callable, TypeVar

from fastapi import HTTPException

from app.persistence.state_repository import configured_database_url

from .memory_repository import MemoryIndexRepository
from .provider import DeterministicLocalProvider
from .service import SemanticIndexService

T = TypeVar("T")


class SemanticIndexRepositoryRuntime:
    """One repository/service runtime shared by semantic indexing and retrieval."""

    def __init__(self, database_url: str | None = None):
        self.database_url = (
            configured_database_url() if database_url is None else database_url
        )
        self.durable_mode_configured = bool(self.database_url)
        self.repository = None
        self.service = None
        self.error: str | None = None
        self.last_durable_refresh_at: str | None = None
        self.last_durable_write_at: str | None = None

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _build_repository(self):
        if self.durable_mode_configured:
            from .postgres_repository import PostgresIndexRepository

            return PostgresIndexRepository(self.database_url)
        return MemoryIndexRepository()

    def _mark_unavailable(self) -> None:
        self.repository = None
        self.service = None
        self.error = "SEMANTIC_INDEX_DATABASE_UNAVAILABLE"

    def _activate(self, repository) -> None:
        self.repository = repository
        self.service = SemanticIndexService(repository, DeterministicLocalProvider())
        self.error = None
        if self.durable_mode_configured and hasattr(repository, "atomic"):
            self.last_durable_refresh_at = self._now()

    def ensure(self):
        if self.repository is not None and self.service is not None:
            return self.repository, self.service
        try:
            repository = self._build_repository()
        except Exception as exc:
            if self.durable_mode_configured:
                self._mark_unavailable()
                raise HTTPException(503, detail={"code": self.error}) from exc
            repository = MemoryIndexRepository()
        self._activate(repository)
        return self.repository, self.service

    def read(self):
        repository, _ = self.ensure()
        try:
            if hasattr(repository, "refresh_for_read"):
                repository.refresh_for_read()
                if self.durable_mode_configured and hasattr(repository, "atomic"):
                    self.last_durable_refresh_at = self._now()
            elif hasattr(repository, "refresh"):
                repository.refresh()
                if self.durable_mode_configured and hasattr(repository, "atomic"):
                    self.last_durable_refresh_at = self._now()
            return repository
        except HTTPException:
            raise
        except Exception as exc:
            if self.durable_mode_configured:
                self._mark_unavailable()
                raise HTTPException(503, detail={"code": self.error}) from exc
            raise

    def write(self, operation: Callable[[], T]) -> T:
        repository, _ = self.ensure()
        try:
            result = (
                repository.atomic(operation)
                if hasattr(repository, "atomic")
                else operation()
            )
            if self.durable_mode_configured and hasattr(repository, "atomic"):
                self.last_durable_write_at = self._now()
                if hasattr(repository, "refresh_for_read"):
                    repository.refresh_for_read()
                self.last_durable_refresh_at = self._now()
            return result
        except HTTPException:
            raise
        except Exception as exc:
            if self.durable_mode_configured:
                self._mark_unavailable()
                raise HTTPException(503, detail={"code": self.error}) from exc
            raise

    def status(self) -> dict[str, object]:
        repository = self.repository
        degraded = self.durable_mode_configured and (
            repository is None or self.service is None
        )
        backend = "UNAVAILABLE"
        durable = False
        indexed = 0
        authorized = 0
        active_models = 0
        if repository is not None:
            backend = type(repository).__name__
            durable = bool(hasattr(repository, "atomic")) and not degraded
            indexed = len(repository.documents)
            authorized = sum(
                1
                for document in repository.documents
                if document.get("metadata", {}).get("display_policy")
                not in (None, "UNKNOWN_REQUIRES_REVIEW")
                and document.get("active", False)
            )
            active_models = len(repository.models)
        elif not self.durable_mode_configured:
            backend = "MemoryIndexRepository"
        return {
            "retrieval_backend": backend,
            "durable": durable,
            "degraded": degraded,
            "unavailable": degraded,
            "indexed_document_count": indexed,
            "display_authorized_count": authorized,
            "active_model_count": active_models,
            "index_error": self.error,
            "last_successful_durable_refresh_at": self.last_durable_refresh_at,
            "last_successful_durable_write_at": self.last_durable_write_at,
        }


RUNTIME = SemanticIndexRepositoryRuntime()


def get_repository_runtime() -> SemanticIndexRepositoryRuntime:
    return RUNTIME
