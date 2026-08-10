from __future__ import annotations
from app.persistence.state_repository import PostgresStateMixin
from .memory_repository import MemoryIndexRepository

class PostgresIndexRepository(PostgresStateMixin, MemoryIndexRepository):
    snapshot_kind = "semantic_index"
    lock_id = 8605
    state_attributes = (
        "models", "runs", "items", "documents", "vectors",
        "lexical", "tombstones", "warnings", "reviews", "cancelled", "_id",
    )

    def __init__(self, database_url: str | None = None) -> None:
        MemoryIndexRepository.__init__(self)
        self.__init_persistence__(database_url)
        self.refresh()
