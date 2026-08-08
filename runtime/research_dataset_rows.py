"""Immutable registered-dataset row storage for the private CALYX Research Station.

Rows may be stored only for an existing project dataset and only when their canonical
SHA-256 exactly matches that dataset's registered checksum. This closes the browser
transport gap without creating a second dataset identity or weakening analysis binding.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime.research_station import ResearchStationService

DATASET_ROWS_SCHEMA_VERSION = "calyx-research-dataset-rows/v1"
DEFAULT_MAX_ROWS = 25_000
DEFAULT_MAX_COLUMNS = 512
DEFAULT_MAX_SERIALIZED_BYTES = 10 * 1024 * 1024


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_rows_sha256(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_stable(rows).encode("utf-8")).hexdigest()


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


def _clean_id(value: str, error_code: str) -> str:
    clean = str(value or "").strip()
    if not clean or any(token in clean for token in ("/", "\\", "..")):
        raise ValueError(error_code)
    return clean


class ResearchDatasetRowStore:
    def __init__(
        self,
        research: ResearchStationService | None = None,
        *,
        maximum_rows: int = DEFAULT_MAX_ROWS,
        maximum_columns: int = DEFAULT_MAX_COLUMNS,
        maximum_serialized_bytes: int = DEFAULT_MAX_SERIALIZED_BYTES,
    ) -> None:
        self.research = research or ResearchStationService()
        self.maximum_rows = maximum_rows
        self.maximum_columns = maximum_columns
        self.maximum_serialized_bytes = maximum_serialized_bytes

    def _dataset(
        self, owner_id: str, project_id: str, dataset_id: str
    ) -> tuple[Path, dict[str, Any]]:
        root, _project = self.research._project(owner_id, project_id)
        clean = _clean_id(dataset_id, "RESEARCH_DATASET_ID_INVALID")
        path = root / "datasets" / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        dataset = json.loads(path.read_text(encoding="utf-8"))
        if dataset.get("project_id") != project_id or dataset.get("dataset_id") != clean:
            raise ValueError("RESEARCH_DATASET_PROJECT_MISMATCH")
        checksum = str(dataset.get("checksum_sha256") or "").casefold()
        if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
            raise ValueError("RESEARCH_DATASET_CHECKSUM_INVALID")
        return root, dataset

    def _validate_rows(self, rows: Any) -> tuple[list[dict[str, Any]], list[str], int]:
        if not isinstance(rows, list) or not rows:
            raise ValueError("RESEARCH_DATASET_ROWS_REQUIRED")
        if len(rows) > self.maximum_rows:
            raise ValueError("RESEARCH_DATASET_ROWS_LIMIT_EXCEEDED")
        if not all(isinstance(row, dict) for row in rows):
            raise TypeError("RESEARCH_DATASET_ROWS_INVALID")
        if any(not all(isinstance(key, str) for key in row) for row in rows):
            raise TypeError("RESEARCH_DATASET_ROW_KEYS_MUST_BE_STRINGS")
        columns = sorted({key for row in rows for key in row})
        if not columns:
            raise ValueError("RESEARCH_DATASET_COLUMNS_REQUIRED")
        if len(columns) > self.maximum_columns:
            raise ValueError("RESEARCH_DATASET_COLUMNS_LIMIT_EXCEEDED")
        try:
            serialized = _stable(rows).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise TypeError("RESEARCH_DATASET_ROWS_NOT_JSON_SERIALIZABLE") from exc
        if len(serialized) > self.maximum_serialized_bytes:
            raise ValueError("RESEARCH_DATASET_ROWS_BYTES_LIMIT_EXCEEDED")
        return rows, columns, len(serialized)

    def put(
        self,
        owner_id: str,
        project_id: str,
        dataset_id: str,
        rows: Any,
        provenance: Any,
    ) -> dict[str, Any]:
        root, dataset = self._dataset(owner_id, project_id, dataset_id)
        normalized_rows, columns, serialized_bytes = self._validate_rows(rows)
        if not isinstance(provenance, dict) or not provenance:
            raise ValueError("RESEARCH_DATASET_ROWS_PROVENANCE_REQUIRED")
        rows_sha256 = canonical_rows_sha256(normalized_rows)
        if rows_sha256 != dataset["checksum_sha256"]:
            raise ValueError("RESEARCH_DATASET_ROWS_CHECKSUM_MISMATCH")
        record = {
            "schema_version": DATASET_ROWS_SCHEMA_VERSION,
            "project_id": project_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_checksum_sha256": dataset["checksum_sha256"],
            "rows_sha256": rows_sha256,
            "row_count": len(normalized_rows),
            "column_count": len(columns),
            "columns": columns,
            "serialized_bytes": serialized_bytes,
            "provenance": provenance,
            "rows": normalized_rows,
            "immutable": True,
            "private_by_default": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        path = root / "dataset_rows" / f"{dataset['dataset_id']}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError("RESEARCH_DATASET_ROWS_IMMUTABLE_CONFLICT")
            return {"created": False, "dataset_rows": existing}
        _atomic(path, record)
        return {"created": True, "dataset_rows": record}

    def get(self, owner_id: str, project_id: str, dataset_id: str) -> dict[str, Any]:
        root, dataset = self._dataset(owner_id, project_id, dataset_id)
        path = root / "dataset_rows" / f"{dataset['dataset_id']}.json"
        if not path.exists():
            raise FileNotFoundError(f"dataset rows unavailable: {dataset['dataset_id']}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("dataset_checksum_sha256") != dataset["checksum_sha256"]:
            raise ValueError("RESEARCH_DATASET_ROWS_REGISTERED_CHECKSUM_DRIFT")
        rows = record.get("rows")
        if not isinstance(rows, list) or canonical_rows_sha256(rows) != dataset["checksum_sha256"]:
            raise ValueError("RESEARCH_DATASET_ROWS_CONTENT_CHECKSUM_DRIFT")
        return record

    def readiness(self, owner_id: str, project_id: str, dataset_id: str) -> dict[str, Any]:
        try:
            record = self.get(owner_id, project_id, dataset_id)
        except FileNotFoundError:
            self._dataset(owner_id, project_id, dataset_id)
            return {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "rows_available": False,
                "immutable": True,
                "private_by_default": True,
                "scientific_publication_authorized": False,
                "knowledge_graph_mutation_authorized": False,
            }
        return {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "rows_available": True,
            "row_count": record["row_count"],
            "column_count": record["column_count"],
            "rows_sha256": record["rows_sha256"],
            "immutable": True,
            "private_by_default": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
