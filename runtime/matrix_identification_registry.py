"""Immutable, versioned registry for governed Matrix Identification candidate sets.

Registry versions are evidence packages, not canonical taxonomy. Each package is
content-addressed, retains provenance, and is immutable once written.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.matrix_identification import Candidate

REGISTRY_SCHEMA_VERSION = "matrix-identification-registry/v1"


@dataclass(frozen=True)
class RegistryCharacter:
    character: str
    label: str
    description: str | None = None
    value_type: str = "categorical"
    weight: float = 1.0
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegistryVersion:
    registry_id: str
    version: str
    title: str
    scope: dict[str, Any]
    characters: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    provenance: dict[str, Any]
    created_at: str
    created_by: str
    checksum_sha256: str
    schema_version: str = REGISTRY_SCHEMA_VERSION
    publication_state: str = "review_required"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def registry_root() -> Path:
    return Path(
        os.getenv("CALYX_MATRIX_REGISTRY_DIR", "/tmp/calyx/matrix-identification-registry")
    )


def _safe_component(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned or any(part in cleaned for part in ("/", "\\", "..")):
        raise ValueError(f"invalid {field}")
    return cleaned


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload)).hexdigest()


def _validate_character(character: RegistryCharacter) -> None:
    if not character.character.strip() or not character.label.strip():
        raise ValueError("character and label are required")
    if character.weight < 0 or character.weight > 100:
        raise ValueError("character weight must be between 0 and 100")
    if character.value_type not in {"categorical", "multi_state", "numeric", "numeric_range"}:
        raise ValueError(f"unsupported character value_type: {character.value_type}")


def _validate_candidate(candidate: Candidate, character_ids: set[str]) -> None:
    if not candidate.taxon_id.strip() or not candidate.scientific_name.strip():
        raise ValueError("candidate taxon_id and scientific_name are required")
    unknown = set(candidate.states) - character_ids
    if unknown:
        raise ValueError(
            "candidate contains states for unregistered characters: "
            + ", ".join(sorted(unknown))
        )


def create_registry_version(
    *,
    registry_id: str,
    version: str,
    title: str,
    scope: dict[str, Any],
    characters: list[RegistryCharacter],
    candidates: list[Candidate],
    provenance: dict[str, Any],
    actor: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Persist one immutable registry version and return its receipt."""
    registry_id = _safe_component(registry_id, "registry_id")
    version = _safe_component(version, "version")
    if not title.strip() or not actor.strip():
        raise ValueError("title and actor are required")
    if not characters:
        raise ValueError("at least one character is required")
    if not candidates:
        raise ValueError("at least one candidate is required")
    if not provenance:
        raise ValueError("registry provenance is required")

    character_ids: set[str] = set()
    for character in characters:
        _validate_character(character)
        if character.character in character_ids:
            raise ValueError(f"duplicate character: {character.character}")
        character_ids.add(character.character)
    candidate_ids: set[str] = set()
    for candidate in candidates:
        _validate_candidate(candidate, character_ids)
        if candidate.taxon_id in candidate_ids:
            raise ValueError(f"duplicate candidate taxon_id: {candidate.taxon_id}")
        candidate_ids.add(candidate.taxon_id)

    unsigned = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_id": registry_id,
        "version": version,
        "title": title.strip(),
        "scope": scope,
        "characters": [asdict(item) for item in characters],
        "candidates": [asdict(item) for item in candidates],
        "provenance": provenance,
        "publication_state": "review_required",
    }
    checksum = _checksum(unsigned)
    record = RegistryVersion(
        registry_id=registry_id,
        version=version,
        title=title.strip(),
        scope=scope,
        characters=unsigned["characters"],
        candidates=unsigned["candidates"],
        provenance=provenance,
        created_at=datetime.now(UTC).isoformat(),
        created_by=actor.strip(),
        checksum_sha256=checksum,
    ).as_dict()

    destination_root = root or registry_root()
    directory = destination_root / registry_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{version}.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing.get("checksum_sha256") == checksum:
            return {"created": False, "record": existing}
        raise ValueError("registry version already exists with different content")

    temp = destination.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(destination)
    return {"created": True, "record": record}


def get_registry_version(
    registry_id: str,
    version: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    registry_id = _safe_component(registry_id, "registry_id")
    version = _safe_component(version, "version")
    path = (root or registry_root()) / registry_id / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"registry version not found: {registry_id}/{version}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_registry_versions(*, root: Path | None = None) -> list[dict[str, Any]]:
    destination_root = root or registry_root()
    if not destination_root.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(destination_root.glob("*/*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records.append(
            {
                "registry_id": record.get("registry_id"),
                "version": record.get("version"),
                "title": record.get("title"),
                "scope": record.get("scope", {}),
                "candidate_count": len(record.get("candidates", [])),
                "character_count": len(record.get("characters", [])),
                "created_at": record.get("created_at"),
                "created_by": record.get("created_by"),
                "checksum_sha256": record.get("checksum_sha256"),
                "publication_state": record.get("publication_state"),
            }
        )
    return sorted(
        records,
        key=lambda item: (
            str(item.get("registry_id", "")).casefold(),
            str(item.get("version", "")).casefold(),
        ),
    )


def candidates_from_registry(record: dict[str, Any]) -> list[Candidate]:
    return [Candidate(**item) for item in record.get("candidates", [])]
