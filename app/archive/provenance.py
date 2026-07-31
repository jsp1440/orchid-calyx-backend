from __future__ import annotations

import uuid
from typing import Any
from psycopg.types.json import Jsonb
from app.archive.registry import ArchiveRegistry

class ProvenanceService:
    def __init__(self, registry: ArchiveRegistry) -> None:
        self.registry = registry

    def record(self, *, document_id: uuid.UUID | None, file_id: uuid.UUID | None, run_id: uuid.UUID,
               event_type: str, source_uri: str | None, details: dict[str, Any]) -> None:
        with self.registry.connection() as conn:
            conn.execute(
                "INSERT INTO archive_provenance (document_id,file_id,import_run_id,event_type,source_uri,details) VALUES (%s,%s,%s,%s,%s,%s)",
                (document_id, file_id, run_id, event_type, source_uri, Jsonb(details)),
            )
            conn.commit()
