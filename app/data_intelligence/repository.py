from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from openpyxl import load_workbook

from .models import DataIntelligenceError


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    dataset_id: str
    version_id: str
    owner: str
    project_id: str
    logical_name: str
    format: str
    content_hash: str
    byte_size: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version_id": self.version_id,
            "owner": self.owner,
            "project_id": self.project_id,
            "logical_name": self.logical_name,
            "format": self.format,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
            "created_at": self.created_at,
        }


class FileDatasetRepository:
    """Tenant/project-scoped, content-addressed dataset and analysis storage."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = RLock()

    @staticmethod
    def _scope_key(value: str, code: str) -> str:
        value = value.strip()
        if not value:
            raise DataIntelligenceError(code)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _digest_part(value: str, code: str, *, lengths: set[int]) -> str:
        value = value.strip().casefold()
        if len(value) not in lengths or any(char not in "0123456789abcdef" for char in value):
            raise DataIntelligenceError(code)
        return value

    def _scope(self, owner: str, project_id: str) -> Path:
        return (
            self.root
            / self._scope_key(owner, "INVALID_OWNER")
            / self._scope_key(project_id, "INVALID_PROJECT_ID")
        )

    def _version_dir(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
    ) -> Path:
        return (
            self._scope(owner, project_id)
            / self._digest_part(dataset_id, "INVALID_DATASET_ID", lengths={32})
            / self._digest_part(version_id, "INVALID_VERSION_ID", lengths={64})
        )

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _dataset_id(owner: str, project_id: str, logical_name: str) -> str:
        payload = (
            f"{owner}\x1f{project_id}\x1f{logical_name.strip().casefold()}".encode()
        )
        return hashlib.sha256(payload).hexdigest()[:32]

    def ingest(
        self,
        *,
        owner: str,
        project_id: str,
        logical_name: str,
        filename: str,
        data: bytes,
    ) -> tuple[DatasetVersion, bool]:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            raise DataIntelligenceError(
                "UNSUPPORTED_DATASET_FORMAT", {"suffix": suffix}
            )
        if not data:
            raise DataIntelligenceError("EMPTY_DATASET")
        if not logical_name.strip():
            raise DataIntelligenceError("DATASET_NAME_REQUIRED")
        dataset_id = self._dataset_id(owner, project_id, logical_name)
        version_id = self._hash(data)
        directory = self._version_dir(owner, project_id, dataset_id, version_id)
        metadata_path = directory / "dataset.json"
        with self._lock:
            if metadata_path.is_file():
                return self.get(owner, project_id, dataset_id, version_id), False
            directory.mkdir(parents=True, exist_ok=True)
            raw_path = directory / f"source{suffix}"
            temp = raw_path.with_suffix(raw_path.suffix + ".tmp")
            temp.write_bytes(data)
            temp.replace(raw_path)
            metadata = DatasetVersion(
                dataset_id=dataset_id,
                version_id=version_id,
                owner=owner,
                project_id=project_id,
                logical_name=logical_name.strip(),
                format=suffix[1:],
                content_hash=version_id,
                byte_size=len(data),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._write_json(metadata_path, metadata.to_dict())
            return metadata, True

    def get(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
    ) -> DatasetVersion:
        path = self._version_dir(owner, project_id, dataset_id, version_id) / "dataset.json"
        if not path.is_file():
            raise DataIntelligenceError("DATASET_VERSION_NOT_FOUND")
        metadata = DatasetVersion(**json.loads(path.read_text(encoding="utf-8")))
        if metadata.owner != owner or metadata.project_id != project_id:
            raise DataIntelligenceError("DATASET_SCOPE_MISMATCH")
        return metadata

    def read_rows(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        metadata = self.get(owner, project_id, dataset_id, version_id)
        directory = self._version_dir(owner, project_id, dataset_id, version_id)
        if metadata.format == "csv":
            raw = (directory / "source.csv").read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise DataIntelligenceError("CSV_MUST_BE_UTF8") from exc
            reader = csv.DictReader(io.StringIO(text, newline=""))
            if not reader.fieldnames:
                raise DataIntelligenceError("DATASET_HEADER_REQUIRED")
            columns = [str(value).strip() for value in reader.fieldnames]
            if any(not value for value in columns) or len(set(columns)) != len(columns):
                raise DataIntelligenceError("DATASET_COLUMNS_INVALID")
            return columns, [dict(row) for row in reader]

        workbook = load_workbook(
            directory / "source.xlsx", read_only=True, data_only=True
        )
        try:
            sheet = workbook.active
            iterator = sheet.iter_rows(values_only=True)
            header = next(iterator, None)
            if not header:
                raise DataIntelligenceError("DATASET_HEADER_REQUIRED")
            columns = [
                str(value).strip() if value is not None else "" for value in header
            ]
            if any(not value for value in columns) or len(set(columns)) != len(columns):
                raise DataIntelligenceError("DATASET_COLUMNS_INVALID")
            rows = [
                {
                    columns[index]: row[index] if index < len(row) else None
                    for index in range(len(columns))
                }
                for row in iterator
            ]
            return columns, rows
        finally:
            workbook.close()

    def profile_path(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
    ) -> Path:
        return self._version_dir(owner, project_id, dataset_id, version_id) / "profile.json"

    def save_profile(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
        profile: dict[str, Any],
    ) -> None:
        self._write_json(
            self.profile_path(owner, project_id, dataset_id, version_id), profile
        )

    def get_profile(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
    ) -> dict[str, Any] | None:
        path = self.profile_path(owner, project_id, dataset_id, version_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def analysis_dir(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
        analysis_id: str,
    ) -> Path:
        return (
            self._version_dir(owner, project_id, dataset_id, version_id)
            / "analyses"
            / self._digest_part(analysis_id, "INVALID_ANALYSIS_ID", lengths={40})
        )

    def save_analysis(
        self,
        *,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
        analysis_id: str,
        manifest: dict[str, Any],
        table_bytes: bytes,
        chart_bytes: bytes | None,
    ) -> dict[str, str]:
        directory = self.analysis_dir(
            owner, project_id, dataset_id, version_id, analysis_id
        )
        directory.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "table.json": self._write_bytes(directory / "table.json", table_bytes)
        }
        if chart_bytes is not None:
            artifacts["chart.svg"] = self._write_bytes(
                directory / "chart.svg", chart_bytes
            )
        final_manifest = {**manifest, "artifact_hashes": artifacts}
        self._write_json(directory / "manifest.json", final_manifest)
        return artifacts

    def get_analysis(
        self,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
        analysis_id: str,
    ) -> dict[str, Any]:
        path = (
            self.analysis_dir(
                owner, project_id, dataset_id, version_id, analysis_id
            )
            / "manifest.json"
        )
        if not path.is_file():
            raise DataIntelligenceError("ANALYSIS_NOT_FOUND")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_workflow(
        self,
        *,
        owner: str,
        project_id: str,
        name: str,
        source_analysis_id: str,
        dataset_id: str,
        version_id: str,
        plan: dict[str, Any],
        plan_fingerprint: str,
    ) -> tuple[dict[str, Any], bool]:
        normalized_name = name.strip()
        if not normalized_name:
            raise DataIntelligenceError("WORKFLOW_NAME_REQUIRED")
        identity = (
            f"{owner}\x1f{project_id}\x1f{normalized_name.casefold()}\x1f"
            f"{source_analysis_id}\x1f{plan_fingerprint}"
        ).encode()
        workflow_id = hashlib.sha256(identity).hexdigest()[:40]
        directory = (
            self._scope(owner, project_id)
            / "workflows"
            / self._digest_part(
                workflow_id,
                "INVALID_WORKFLOW_ID",
                lengths={40},
            )
        )
        path = directory / "workflow.json"
        with self._lock:
            if path.is_file():
                return self.get_workflow(
                    owner,
                    project_id,
                    workflow_id,
                ), False
            directory.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "schema_version": "calyx-data-workflow-001.1",
                "workflow_id": workflow_id,
                "owner": owner,
                "project_id": project_id,
                "name": normalized_name,
                "source_analysis_id": source_analysis_id,
                "dataset": {
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                },
                "plan": plan,
                "plan_fingerprint": plan_fingerprint,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_json(path, payload)
            return {**payload, "review_state": "draft", "review_events": []}, True

    def get_workflow(
        self,
        owner: str,
        project_id: str,
        workflow_id: str,
    ) -> dict[str, Any]:
        directory = (
            self._scope(owner, project_id)
            / "workflows"
            / self._digest_part(
                workflow_id,
                "INVALID_WORKFLOW_ID",
                lengths={40},
            )
        )
        path = directory / "workflow.json"
        if not path.is_file():
            raise DataIntelligenceError("WORKFLOW_NOT_FOUND")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("owner") != owner or payload.get("project_id") != project_id:
            raise DataIntelligenceError("WORKFLOW_SCOPE_MISMATCH")
        events_path = directory / "review-events.json"
        events = (
            json.loads(events_path.read_text(encoding="utf-8"))
            if events_path.is_file()
            else []
        )
        if not isinstance(events, list):
            raise DataIntelligenceError("WORKFLOW_REVIEW_LEDGER_INVALID")
        state = "submitted" if any(
            event.get("action") == "submitted"
            for event in events
            if isinstance(event, dict)
        ) else "draft"
        return {
            **payload,
            "review_state": state,
            "review_events": events,
        }

    def submit_workflow(
        self,
        *,
        owner: str,
        project_id: str,
        workflow_id: str,
        actor: str,
    ) -> dict[str, Any]:
        workflow = self.get_workflow(owner, project_id, workflow_id)
        directory = (
            self._scope(owner, project_id)
            / "workflows"
            / workflow_id
        )
        path = directory / "review-events.json"
        event_id = hashlib.sha256(
            f"{workflow_id}\x1fsubmitted\x1f{actor}".encode()
        ).hexdigest()
        with self._lock:
            current = self.get_workflow(owner, project_id, workflow_id)
            if any(
                event.get("event_id") == event_id
                for event in current["review_events"]
                if isinstance(event, dict)
            ):
                return current
            events = [
                *current["review_events"],
                {
                    "event_id": event_id,
                    "action": "submitted",
                    "actor": actor,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            self._write_json(path, events)
        return self.get_workflow(owner, project_id, workflow_id)

    def read_artifact(
        self,
        *,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
        analysis_id: str,
        artifact_name: str,
    ) -> bytes:
        manifest = self.get_analysis(
            owner,
            project_id,
            dataset_id,
            version_id,
            analysis_id,
        )
        artifact_hashes = manifest.get("artifact_hashes")
        if not isinstance(artifact_hashes, dict):
            raise DataIntelligenceError("ARTIFACT_MANIFEST_INVALID")
        expected_hash = artifact_hashes.get(artifact_name)
        if not isinstance(expected_hash, str):
            raise DataIntelligenceError(
                "ARTIFACT_NOT_FOUND", {"artifact_name": artifact_name}
            )
        path = (
            self.analysis_dir(
                owner,
                project_id,
                dataset_id,
                version_id,
                analysis_id,
            )
            / artifact_name
        )
        if not path.is_file():
            raise DataIntelligenceError(
                "ARTIFACT_NOT_FOUND", {"artifact_name": artifact_name}
            )
        data = path.read_bytes()
        actual_hash = self._hash(data)
        if actual_hash != expected_hash:
            raise DataIntelligenceError(
                "ARTIFACT_INTEGRITY_FAILURE",
                {
                    "artifact_name": artifact_name,
                    "expected_hash": expected_hash,
                    "actual_hash": actual_hash,
                },
            )
        return data

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> str:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def _write_json(
        cls,
        path: Path,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> None:
        data = (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        ).encode("utf-8")
        cls._write_bytes(path, data)
