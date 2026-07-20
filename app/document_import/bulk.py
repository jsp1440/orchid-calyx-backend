from __future__ import annotations

from collections import Counter
from time import monotonic
from typing import Any

from .drive import format_for


class BulkImportService:
    """Resumable orchestration that delegates document work to BUILD-082."""

    def __init__(self, repository: Any, scan_service: Any, source_repository: Any, importer: Any):
        self.repository = repository
        self.scan_service = scan_service
        self.source_repository = source_repository
        self.importer = importer

    def preview(self, source_id: str, actor: str) -> dict[str, Any]:
        source = self.source_repository.get_source(source_id)
        if not source or source["source_type"] != "GOOGLE_DRIVE":
            raise LookupError("GOOGLE_DRIVE_SOURCE_NOT_FOUND")
        if not self.importer.repository.actor_owns_source(actor, source_id):
            raise PermissionError("SOURCE_OWNERSHIP_REQUIRED")
        scan = self.scan_service.scan(source_id, list(source["configuration"].get("folder_ids", [])))
        candidates = self.repository.candidates(source_id)
        items = []
        for row in candidates:
            try:
                format_for(row["mime_type"])
                if row["status"] == "DUPLICATE": classification = "DUPLICATE"
                elif row["revision_id"] is None: classification = "NEW"
                elif row["modified_at"] and row["revision_modified_at"] == row["modified_at"].isoformat(): classification = "UNCHANGED"
                else: classification = "UPDATED"
            except ValueError:
                classification = "UNSUPPORTED"
            items.append({"registry_id":row["inventory_id"],"filename":row["filename"],"folder":row["folder_path"],
                "mime_type":row["mime_type"],"classification":classification})
        run_id = self.repository.create_plan(source_id, actor, items)
        counts = Counter(item["classification"] for item in items)
        types = Counter(item["mime_type"] for item in items)
        return {"bulk_run_id":run_id,"scan":scan.__dict__,"items":items,"counts":dict(counts),"counts_by_type":dict(types)}

    def execute(self, run_id: int, actor: str) -> dict[str, Any]:
        source_id = self.repository.source_id(run_id)
        if not self.importer.repository.actor_owns_source(actor, source_id):
            raise PermissionError("SOURCE_OWNERSHIP_REQUIRED")
        started = monotonic(); self.repository.start(run_id, actor)
        for item in self.repository.pending(run_id):
            if self.repository.cancelled(run_id): break
            if item["classification"] not in {"NEW","UPDATED"}:
                state = "DUPLICATE" if item["classification"] == "DUPLICATE" else "SKIPPED"
                self.repository.record(run_id, item["registry_id"], state, None, None)
                continue
            result = self.importer.import_one(item["registry_id"], actor)
            if result.state.value in {"IMPORTED"}:
                state = "UPDATED" if item["classification"] == "UPDATED" else "IMPORTED"
            elif result.state.value == "DUPLICATE": state = "DUPLICATE"
            elif result.state.value == "UNCHANGED": state = "SKIPPED"
            else: state = "FAILED"
            self.repository.record(run_id, item["registry_id"], state, result.error_code, result.as_dict())
        return self.repository.finish(run_id, round((monotonic()-started)*1000, 3))

    def resume(self, run_id: int, actor: str) -> dict[str, Any]:
        return self.execute(run_id, actor)

    def cancel(self, run_id: int, actor: str) -> dict[str, Any]:
        source_id = self.repository.source_id(run_id)
        if not self.importer.repository.actor_owns_source(actor, source_id):
            raise PermissionError("SOURCE_OWNERSHIP_REQUIRED")
        return self.repository.cancel(run_id, actor)

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.history(limit)
