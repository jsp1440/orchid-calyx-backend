"""Governed Matrix Identification sessions and deterministic next-observation selection."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.matrix_identification import Observation, rank_candidates
from runtime.matrix_identification_registry import (
    candidates_from_registry,
    get_registry_version,
)
from runtime.matrix_identification_session_store import (
    configured_matrix_session_store,
    matrix_session_persistence_status,
)

SESSION_SCHEMA_VERSION = "matrix-identification-session/v1"


def session_root() -> Path:
    return Path(
        os.getenv("CALYX_MATRIX_SESSION_DIR", "/tmp/calyx/matrix-identification-sessions")
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write(record: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    return configured_matrix_session_store(root=root).save(record)


def _assert_session_owner(record: dict[str, Any], access_actor: str | None) -> None:
    """Fail closed across owner-session boundaries without disclosing existence.

    `access_actor=None` is reserved for trusted internal/API-key callers whose
    authorization boundary is enforced at the router or service layer.
    """
    if access_actor is None:
        return
    expected = str(record.get("actor") or "").strip()
    supplied = str(access_actor).strip()
    if not expected or not supplied or supplied != expected:
        raise FileNotFoundError(
            f"identification session not found: {record.get('session_id', '')}"
        )


def get_session(
    session_id: str,
    *,
    root: Path | None = None,
    access_actor: str | None = None,
) -> dict[str, Any]:
    record = configured_matrix_session_store(root=root).get(
        session_id,
        access_actor=access_actor,
    )
    if record is None:
        raise FileNotFoundError(f"identification session not found: {session_id}")
    _assert_session_owner(record, access_actor)
    return record


def persistence_status() -> dict[str, Any]:
    return matrix_session_persistence_status()


def _bound_registry(
    record: dict[str, Any], *, registry_root: Path | None = None
) -> dict[str, Any]:
    registry_ref = record["registry"]
    registry = get_registry_version(
        registry_ref["registry_id"], registry_ref["version"], root=registry_root
    )
    if registry.get("checksum_sha256") != registry_ref.get("checksum_sha256"):
        raise ValueError("registry checksum drift detected for identification session")
    return registry


def create_session(
    *,
    registry_id: str,
    version: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    root: Path | None = None,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    actor = str(actor).strip()
    if not actor:
        raise ValueError("authenticated actor is required")
    registry = get_registry_version(registry_id, version, root=registry_root)
    now = _now()
    record = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": str(uuid.uuid4()),
        "registry": {
            "registry_id": registry["registry_id"],
            "version": registry["version"],
            "checksum_sha256": registry["checksum_sha256"],
            "publication_state": registry.get("publication_state"),
            "scope": registry.get("scope", {}),
        },
        "actor": actor,
        "metadata": metadata or {},
        "observations": [],
        "revision": 0,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "latest_evaluation": None,
        "next_observation": None,
    }
    return _write(record, root=root)


def add_observation(
    session_id: str,
    *,
    character: str,
    value: Any,
    certainty: str = "certain",
    weight: float | None = None,
    source: dict[str, Any] | None = None,
    actor: str | None = None,
    access_actor: str | None = None,
    root: Path | None = None,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    record = get_session(session_id, root=root, access_actor=access_actor)
    registry = _bound_registry(record, registry_root=registry_root)
    allowed_characters = {
        item.get("character") for item in registry.get("characters", []) if item.get("character")
    }
    if character not in allowed_characters:
        raise ValueError(
            f"character is not defined by bound registry {record['registry']['registry_id']}@{record['registry']['version']}: {character}"
        )
    recorded_by = str(actor or record.get("actor") or "").strip()
    if not recorded_by:
        raise ValueError("authenticated actor is required for observation provenance")
    record["revision"] = int(record.get("revision", 0)) + 1
    record.setdefault("observations", []).append(
        {
            "observation_id": str(uuid.uuid4()),
            "revision": record["revision"],
            "character": character,
            "value": value,
            "certainty": certainty,
            "weight": weight,
            "source": source or {"kind": "user_observation"},
            "recorded_by": recorded_by,
            "review_state": "observed",
            "created_at": _now(),
        }
    )
    record["updated_at"] = _now()
    return _write(record, root=root)


def _normalized_state(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def recommend_next_observation(
    registry: dict[str, Any],
    ranked_candidates: list[dict[str, Any]],
    observed_characters: set[str],
    *,
    candidate_limit: int = 10,
) -> dict[str, Any] | None:
    """Choose the unobserved positive-weight character with strongest discrimination."""
    if not ranked_candidates:
        return None

    candidate_ids = {
        item["taxon_id"] for item in ranked_candidates[:candidate_limit] if item.get("taxon_id")
    }
    candidates = [
        item for item in registry.get("candidates", []) if item.get("taxon_id") in candidate_ids
    ]
    if len(candidates) < 2:
        return None

    character_meta = {
        item.get("character"): item for item in registry.get("characters", []) if item.get("character")
    }
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for character, meta in character_meta.items():
        if character in observed_characters:
            continue
        source_weight = meta.get("weight")
        weight = float(source_weight) if source_weight is not None else 1.0
        if weight <= 0:
            continue
        states = [candidate.get("states", {}).get(character) for candidate in candidates]
        present = [state for state in states if state is not None]
        if len(present) < 2:
            continue
        distinct = len({_normalized_state(state) for state in present})
        if distinct < 2:
            continue
        coverage = len(present) / len(candidates)
        discrimination = (distinct - 1) / max(len(present) - 1, 1)
        score = coverage * discrimination * weight
        scored.append(
            (
                score,
                character,
                {
                    "character": character,
                    "label": meta.get("label") or character.replace("_", " "),
                    "description": meta.get("description"),
                    "value_type": meta.get("value_type", "categorical"),
                    "concept_id": meta.get("concept_id"),
                    "matrix_weight": weight,
                    "candidate_coverage": round(coverage, 6),
                    "distinct_state_count": distinct,
                    "candidate_count": len(candidates),
                    "selection_score": round(score, 6),
                    "reason_code": "highest_deterministic_discrimination",
                    "explanation_boundary": (
                        "Calyx may explain this recommendation but may not alter the selected "
                        "character without returning a separately labeled inference."
                    ),
                },
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2]


def evaluate_session(
    session_id: str,
    *,
    limit: int = 20,
    access_actor: str | None = None,
    root: Path | None = None,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    record = get_session(session_id, root=root, access_actor=access_actor)
    registry = _bound_registry(record, registry_root=registry_root)
    registry_ref = record["registry"]

    default_weights = {
        item["character"]: float(item.get("weight", 1.0))
        for item in registry.get("characters", [])
        if item.get("character")
    }
    observations = [
        Observation(
            character=item["character"],
            value=item.get("value"),
            certainty=item.get("certainty", "certain"),
            weight=(
                float(item["weight"])
                if item.get("weight") is not None
                else default_weights.get(item["character"], 1.0)
            ),
        )
        for item in record.get("observations", [])
    ]
    report = rank_candidates(observations, candidates_from_registry(registry), limit=limit)
    report["registry"] = registry_ref
    report["session_id"] = session_id
    report["revision"] = record.get("revision", 0)

    next_observation = recommend_next_observation(
        registry,
        report.get("candidates", []),
        {item.character for item in observations},
    )
    record["latest_evaluation"] = report
    record["next_observation"] = next_observation
    record["updated_at"] = _now()
    _write(record, root=root)
    return {
        "session": record,
        "report": report,
        "next_observation": next_observation,
    }
