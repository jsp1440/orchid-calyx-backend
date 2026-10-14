"""Restart-safe file repository for evidence feedback cases and versions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Protocol, TypeVar

from .models import EvidenceFeedbackCase, EvidenceObjectVersion, canonical_json

T = TypeVar("T")

# Stable 503 code when the configured durable store cannot be reached.
DATABASE_UNAVAILABLE_CODE = "EVIDENCE_FEEDBACK_DATABASE_UNAVAILABLE"


class EvidenceFeedbackRepositoryError(ValueError):
    pass


class EvidenceFeedbackStoreUnavailable(RuntimeError):
    """The configured durable store is unreachable or unusable.

    Deliberately not a ``ValueError``: callers must fail closed (HTTP 503)
    rather than treat an outage as a client error or fall back to another
    store, which would split feedback between two places.
    """

    def __init__(self, code: str = DATABASE_UNAVAILABLE_CODE) -> None:
        super().__init__(code)


class EvidenceFeedbackRepository(Protocol):
    """Contract shared by the file and PostgreSQL stores."""

    def atomic(
        self, operation: Callable[[], T], *, lock_key: str | None = None
    ) -> T: ...

    def save_case(self, case: EvidenceFeedbackCase) -> None: ...

    def get_case(self, case_id: str) -> EvidenceFeedbackCase: ...

    def find_by_fingerprint(
        self, fingerprint: str
    ) -> EvidenceFeedbackCase | None: ...

    def append_event(
        self,
        *,
        case_id: str,
        event: str,
        timestamp: str,
        actor_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None: ...

    def list_events(self, case_id: str) -> list[dict[str, Any]]: ...

    def list_cases(
        self,
        *,
        status: str | None,
        object_type: str | None,
        limit: int,
        before: tuple[str, str] | None,
    ) -> list[EvidenceFeedbackCase]: ...

    def count_case_events(
        self, case_ids: Sequence[str], event: str
    ) -> dict[str, int]: ...

    def save_object_version(
        self, version: EvidenceObjectVersion
    ) -> EvidenceObjectVersion: ...

    def get_object_version(
        self, object_id: str, version_hash: str
    ) -> EvidenceObjectVersion: ...

    def list_object_versions(
        self, object_id: str
    ) -> list[EvidenceObjectVersion]: ...


def review_order_key(case: EvidenceFeedbackCase) -> tuple[str, str]:
    """Owner review queue order: newest ``created_at`` first, then case id.

    Both stores compare these strings by code point (PostgreSQL uses the "C"
    collation), so the order and every cursor are identical across stores.
    """

    return (case.created_at, case.case_id)


def normalized_key(value: str, *, code: str) -> str:
    """Identity used by every store: surrounding whitespace is not identity.

    An identifier with NUL, another control character or any non-printable
    character is refused with ``<FIELD>_INVALID_CHARACTERS`` (``code`` with its
    ``_REQUIRED`` suffix replaced), a client error in both stores: PostgreSQL
    cannot store NUL in text, and it must never surface as a 503 outage.
    """

    normalized = value.strip()
    if not normalized:
        raise EvidenceFeedbackRepositoryError(code)
    if not normalized.isprintable():
        raise EvidenceFeedbackRepositoryError(
            code.removesuffix("_REQUIRED") + "_INVALID_CHARACTERS"
        )
    return normalized


# Line structure is legitimate in free text; every other control character is not.
_FREE_TEXT_WHITESPACE = frozenset("\t\n\r")


def has_disallowed_text_characters(value: str) -> bool:
    """True when free text holds NUL, another control character or a lone surrogate.

    Tab, newline and carriage return are allowed. NUL cannot be stored in a
    PostgreSQL ``text`` or ``jsonb`` value, so accepting it would make one
    store answer 503 where the other stores the text.
    """

    return any(
        unicodedata.category(char) in {"Cc", "Cs"} and char not in _FREE_TEXT_WHITESPACE
        for char in value
    )


def validate_free_text(value: str | None, *, code: str) -> None:
    """Refuse free text with disallowed characters (``code`` is the 422 code)."""

    if value is not None and has_disallowed_text_characters(value):
        raise EvidenceFeedbackRepositoryError(code)


def validate_label(value: str | None, *, code: str) -> None:
    """Refuse a short label (severity, defect kind, partner id) that is not printable."""

    if value is not None and not value.isprintable():
        raise EvidenceFeedbackRepositoryError(code)


def normalized_version_hash(version_hash: str) -> str:
    normalized = version_hash.strip().casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise EvidenceFeedbackRepositoryError("INVALID_OBJECT_VERSION_HASH")
    return normalized


def payload_version_hash(version: EvidenceObjectVersion) -> str:
    """Verify ``version.version_hash`` is the content hash of its payload."""

    expected = hashlib.sha256(
        canonical_json(version.payload).encode("utf-8")
    ).hexdigest()
    if version.version_hash != expected:
        raise EvidenceFeedbackRepositoryError("OBJECT_VERSION_HASH_MISMATCH")
    return expected


def is_same_version(
    persisted: EvidenceObjectVersion, candidate: EvidenceObjectVersion
) -> bool:
    """True when ``candidate`` re-presents the persisted content version.

    ``created_at`` is the first-registration time and is not part of the
    version identity. A caller that makes no lineage claim
    (``previous_version_hash is None``) does not contradict stored lineage;
    a conflicting lineage claim, object type or payload does.
    """

    return (
        persisted.object_id == candidate.object_id
        and persisted.object_type is candidate.object_type
        and persisted.version_hash == candidate.version_hash
        and persisted.payload == candidate.payload
        and candidate.previous_version_hash
        in {None, persisted.previous_version_hash}
    )


# One writer lock per resolved root, shared by every repository instance in
# the process. Each request builds its own repository, so a per-instance lock
# would let concurrent requests interleave (double-applied decisions, torn
# case files).
_ROOT_LOCKS: dict[str, RLock] = {}
_ROOT_LOCKS_GUARD = Lock()


def _root_lock(root: Path) -> RLock:
    key = os.path.realpath(root)
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = _ROOT_LOCKS[key] = RLock()
        return lock


class FileEvidenceFeedbackRepository:
    """Content-addressed storage with atomic snapshots and append-only events.

    Durable only when ``root`` is on persistent storage. A deployment with a
    configured database uses ``PostgresEvidenceFeedbackRepository`` instead.
    Writers are serialized per root across every instance in this process;
    the file store is the local/dev store, so it does not coordinate separate
    processes (the PostgreSQL store does, with advisory locks).
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = _root_lock(self.root)

    def atomic(
        self, operation: Callable[[], T], *, lock_key: str | None = None
    ) -> T:
        """Run ``operation`` serialized against other writers in this process."""

        with self._lock:
            return operation()

    @staticmethod
    def _key(value: str, *, code: str) -> str:
        normalized = normalized_key(value, code=code)
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

    def list_cases(
        self,
        *,
        status: str | None,
        object_type: str | None,
        limit: int,
        before: tuple[str, str] | None,
    ) -> list[EvidenceFeedbackCase]:
        """Cases newest first, strictly after the ``before`` keyset cursor.

        A full scan: the file store is the local/dev store. The durable
        PostgreSQL store answers the same query from an index.
        """

        directory = self.root / "cases"
        if not directory.is_dir():
            return []
        cases = [
            EvidenceFeedbackCase.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
            for path in directory.glob("*.json")
        ]
        selected = [
            case
            for case in cases
            if (status is None or case.status.value == status)
            and (object_type is None or case.object_type.value == object_type)
            and (before is None or review_order_key(case) < before)
        ]
        selected.sort(key=review_order_key, reverse=True)
        return selected[: max(0, limit)]

    def count_case_events(
        self, case_ids: Sequence[str], event: str
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case_id in case_ids:
            path = (
                self.root
                / "events"
                / f"{self._key(case_id, code='CASE_ID_REQUIRED')}.jsonl"
            )
            total = 0
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip() and json.loads(line).get("event") == event:
                        total += 1
            counts[case_id] = total
        return counts

    _is_same_version = staticmethod(is_same_version)

    def save_object_version(
        self, version: EvidenceObjectVersion
    ) -> EvidenceObjectVersion:
        """Persist ``version`` once and return the authoritative stored record.

        Re-registering the same displayed content is idempotent and returns the
        original record unchanged (the product registers the displayed version
        before every feedback submission).
        """

        expected = payload_version_hash(version)
        path = self._object_dir(version.object_id) / "versions" / f"{expected}.json"
        with self._lock:
            if path.is_file():
                persisted = EvidenceObjectVersion.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if not self._is_same_version(persisted, version):
                    raise EvidenceFeedbackRepositoryError(
                        "OBJECT_VERSION_IMMUTABILITY_VIOLATION"
                    )
                return persisted
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
            return version

    def get_object_version(
        self, object_id: str, version_hash: str
    ) -> EvidenceObjectVersion:
        normalized = normalized_version_hash(version_hash)
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
        """Atomically replace ``path``: readers see the old or new file, never part.

        The temporary file has a unique name in the same directory (so the
        final ``os.replace`` is a same-filesystem rename) and is flushed to
        disk before the swap.
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(canonical_json(value) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
