"""Checksum-bound private tabular dataset snapshots for CALYX-617."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime.research_analysis_workflow import (
    ResearchAnalysisWorkflowService,
    canonical_rows_sha256,
)
from runtime.scientific_analysis import MAX_COLUMNS, MAX_ROWS

DATASET_SNAPSHOT_SCHEMA_VERSION = "calyx-scientific-dataset-snapshot/v1"
MAX_SNAPSHOT_BYTES = 5_000_000


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _clean_dataset_id(dataset_id: str) -> str:
    clean = str(dataset_id or "").strip()
    if not clean or any(token in clean for token in ("/", "\\", "..")):
        raise ValueError("ANALYSIS_DATASET_SNAPSHOT_ID_INVALID")
    return clean


def _normalize_rows(rows: Any) -> tuple[list[dict[str, Any]], list[str], int]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("ANALYSIS_DATASET_SNAPSHOT_ROWS_REQUIRED")
    if len(rows) > MAX_ROWS:
        raise ValueError("ANALYSIS_DATASET_SNAPSHOT_ROW_LIMIT")
    normalized: list[dict[str, Any]] = []
    columns: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("ANALYSIS_DATASET_SNAPSHOT_ROW_OBJECT_REQUIRED")
        normalized_row = {str(key): value for key, value in row.items()}
        columns.update(normalized_row)
        if len(columns) > MAX_COLUMNS:
            raise ValueError("ANALYSIS_DATASET_SNAPSHOT_COLUMN_LIMIT")
        normalized.append(normalized_row)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError("ANALYSIS_DATASET_SNAPSHOT_BYTE_LIMIT")
    return normalized, sorted(columns), len(encoded)


class ScientificDatasetSnapshotService:
    """Persist exact rows only after they match a registered Research Station dataset."""

    def __init__(self, workflow: ResearchAnalysisWorkflowService | None = None) -> None:
        self.workflow = workflow or ResearchAnalysisWorkflowService()

    def _root(self, owner_id: str, project_id: str) -> Path:
        return self.workflow._project_root(owner_id, project_id) / "analysis_dataset_snapshots"

    def _path(self, owner_id: str, project_id: str, dataset_id: str) -> Path:
        return self._root(owner_id, project_id) / f"{_clean_dataset_id(dataset_id)}.json"

    def put(
        self,
        owner_id: str,
        project_id: str,
        dataset_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        clean = _clean_dataset_id(dataset_id)
        dataset = self.workflow._dataset(owner_id, project_id, clean)
        rows, columns, encoded_bytes = _normalize_rows(payload.get("rows"))
        rows_sha256 = canonical_rows_sha256(rows)
        registered_sha256 = str(dataset["checksum_sha256"]).casefold()
        if rows_sha256 != registered_sha256:
            raise ValueError("ANALYSIS_DATASET_SNAPSHOT_CHECKSUM_MISMATCH")
        recorded_by = " ".join(str(payload.get("recorded_by") or "").strip().split())
        recorded_at = " ".join(str(payload.get("recorded_at") or "").strip().split())
        provenance = dict(payload.get("provenance") or {})
        if not recorded_by or not recorded_at or not provenance:
            raise ValueError("ANALYSIS_DATASET_SNAPSHOT_PROVENANCE_REQUIRED")
        record = {
            "schema_version": DATASET_SNAPSHOT_SCHEMA_VERSION,
            "project_id": project_id,
            "dataset_id": clean,
            "dataset_title": dataset.get("title"),
            "registered_checksum_sha256": registered_sha256,
            "rows_sha256": rows_sha256,
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": columns,
            "encoded_json_bytes": encoded_bytes,
            "rows": rows,
            "dataset_provenance": dataset.get("provenance") or {},
            "snapshot_provenance": provenance,
            "recorded_by": recorded_by,
            "recorded_at": recorded_at,
            "private": True,
            "immutable": True,
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        path = self._path(owner_id, project_id, clean)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                existing.get("rows_sha256") != rows_sha256
                or existing.get("registered_checksum_sha256") != registered_sha256
                or existing.get("rows") != rows
            ):
                raise ValueError("ANALYSIS_DATASET_SNAPSHOT_IMMUTABLE_CONFLICT")
            return {"created": False, "snapshot": existing}
        _atomic(path, record)
        return {"created": True, "snapshot": record}

    def get(
        self,
        owner_id: str,
        project_id: str,
        dataset_id: str,
        *,
        include_rows: bool = True,
    ) -> dict[str, Any]:
        clean = _clean_dataset_id(dataset_id)
        dataset = self.workflow._dataset(owner_id, project_id, clean)
        path = self._path(owner_id, project_id, clean)
        if not path.exists():
            raise FileNotFoundError(clean)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("registered_checksum_sha256") != dataset.get("checksum_sha256"):
            raise ValueError("ANALYSIS_DATASET_SNAPSHOT_REGISTRATION_DRIFT")
        if include_rows:
            return record
        return {key: value for key, value in record.items() if key != "rows"}

    def list(self, owner_id: str, project_id: str) -> dict[str, Any]:
        self.workflow._project_root(owner_id, project_id)
        root = self._root(owner_id, project_id)
        items: list[dict[str, Any]] = []
        if root.exists():
            for path in sorted(root.glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                items.append({key: value for key, value in record.items() if key != "rows"})
        return {
            "schema_version": DATASET_SNAPSHOT_SCHEMA_VERSION,
            "project_id": project_id,
            "items": items,
            "count": len(items),
            "rows_are_returned_only_by_explicit_snapshot_get": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def readiness(self, owner_id: str, project_id: str) -> dict[str, Any]:
        listing = self.list(owner_id, project_id)
        return {
            "schema_version": DATASET_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_count": listing["count"],
            "registered_dataset_checksum_required": True,
            "max_rows": MAX_ROWS,
            "max_columns": MAX_COLUMNS,
            "max_snapshot_bytes": MAX_SNAPSHOT_BYTES,
            "private_snapshot_storage": True,
            "arbitrary_code_execution": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
