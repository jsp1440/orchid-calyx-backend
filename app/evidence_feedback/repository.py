"""Restart-safe file repository for evidence feedback cases and versions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any

from .models import EvidenceFeedbackCase, EvidenceObjectVersion, canonical_json


class EvidenceFeedbackRepositoryError(ValueError):
    pass


class FileEvidenceFeedbackRepository:
    """Content-addressed storage with atomic snapshots and append-only events."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = RLock()

    @staticmethod
    def _key(value: str, *, code: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise EvidenceFeedbackRepositoryError(code)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _case_path(self, case_id: str) -> Path:
        return self.root / "cases" / f"{self._key(case_id, code='CASE_ID_REQUIRED')}.json"

    def _fingerprint_path(self, fingerprint: str) -> Path:
        return (
            self.root
            / "fingerprints"
            / f"{self._key(fingerprint, code='FINGERPRINT_REQUIRED')}.json"
        )

    def _object_dir(self, object_id: str) -> Path:
        return self.root / "objects" / self._key(object_id, code="OBJECT_ID_REQUIRED")

    def save_case(self, case: EvidenceFeedbackCase) -> None:
        with self._lock:
            existing = self.find_by_fingerprint(case.fingerprint)
            if existing is not None and existing.case_id != case.case_id:
                raise EvidenceFeedbackRepositoryError("FINGERPRINT_ALREADY_BOUND")
            self._write_json(self._case_path(case.case_id), case.to_dict())
            self._write_json(
                self._fingerprint_path(case.fingerprint),
                {"case_id": case.case_id},
            )

    def get_case(self, case_id: str) -> EvidenceFeedbackCase:
        path = self._case_path(case_id)
        if not path.is_file():
            raise EvidenceFeedbackRepositoryError("CASE_NOT_FOUND")
        return EvidenceFeedbackCase.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def find_by_fingerprint(
        self, fingerprint: str
    ) -> EvidenceFeedbackCase | None:
        path = self._fingerprint_path(fingerprint)
        if not path.is_file():
            return None
        pointer = json.loads(path.read_text(encoding="utf-8"))
        return self.get_case(str(pointer["case_id"]))

    def append_event(
        self,
        *,
        case_id: str,
        event: str,
        timestamp: str,
        actor_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.get_case(case_id)
        record = {
            "case_id": case_id,
            "event": event,
            "timestamp": timestamp,
            "actor_id": actor_id,
            "details": details or {},
        }
        path = self.root / "events" / f"{self._key(case_id, code='CASE_ID_REQUIRED')}.jsonl"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(record))
                handle.write("\n")

    def list_events(self, case_id: str) -> list[dict[str, Any]]:
        self.get_case(case_id)
        path = self.root / "events" / f"{self._key(case_id, code='CASE_ID_REQUIRED')}.jsonl"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save_object_version(self, version: EvidenceObjectVersion) -> None:
        expected = hashlib.sha256(
            canonical_json(version.payload).encode("utf-8")
        ).hexdigest()
        if version.version_hash != expected:
            raise EvidenceFeedbackRepositoryError("OBJECT_VERSION_HASH_MISMATCH")
        path = self._object_dir(version.object_id) / "versions" / f"{expected}.json"
        with self._lock:
            if path.is_file():
                persisted = EvidenceObjectVersion.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if persisted != version:
                    raise EvidenceFeedbackRepositoryError(
                        "OBJECT_VERSION_IMMUTABILITY_VIOLATION"
                    )
                return
            if version.previous_version_hash is not None:
                self.get_object_version(
                    version.object_id,
                    version.previous_version_hash,
                )
            self._write_json(path, version.to_dict())
            self._write_json(
                self._object_dir(version.object_id) / "latest.json",
                {"version_hash": expected},
            )

    def get_object_version(
        self, object_id: str, version_hash: str
    ) -> EvidenceObjectVersion:
        normalized = version_hash.strip().casefold()
        if len(normalized) != 64 or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise EvidenceFeedbackRepositoryError("INVALID_OBJECT_VERSION_HASH")
        path = self._object_dir(object_id) / "versions" / f"{normalized}.json"
        if not path.is_file():
            raise EvidenceFeedbackRepositoryError("OBJECT_VERSION_NOT_FOUND")
        return EvidenceObjectVersion.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def list_object_versions(self, object_id: str) -> list[EvidenceObjectVersion]:
        directory = self._object_dir(object_id) / "versions"
        if not directory.is_dir():
            return []
        return [
            EvidenceObjectVersion.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
            for path in sorted(directory.glob("*.json"))
        ]

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            canonical_json(value) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
