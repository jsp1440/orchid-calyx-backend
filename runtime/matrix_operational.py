"""Operational Matrix Identification sessions built on the canonical Matrix MVP/registry."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from runtime.matrix_identification import Candidate, Observation, rank_candidates
from runtime.matrix_identification_registry import (
    candidates_from_registry,
    get_registry_version,
)

OPERATIONAL_SCHEMA_VERSION = "matrix-identification-operational/v1"
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
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


def _safe(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned or SAFE_ID_RE.sub("_", cleaned) != cleaned:
        raise ValueError(f"invalid {field}")
    return cleaned


def session_root() -> Path:
    return Path(os.getenv("CALYX_MATRIX_SESSION_DIR", "/tmp/calyx/matrix-identification-sessions"))


def _candidate_aliases(candidate: Candidate) -> set[str]:
    aliases = {candidate.scientific_name.casefold()}
    provenance = candidate.provenance or {}
    for value in provenance.get("synonyms", []):
        if str(value).strip():
            aliases.add(str(value).strip().casefold())
    return aliases


def resolve_candidate_name(candidates: list[Candidate], label: str) -> dict[str, Any]:
    needle = label.strip().casefold()
    if not needle:
        raise ValueError("candidate label is required")
    matches = [candidate for candidate in candidates if needle in _candidate_aliases(candidate)]
    if len(matches) == 1:
        candidate = matches[0]
        return {
            "state": "matched",
            "canonical_taxon_id": candidate.taxon_id,
            "scientific_name": candidate.scientific_name,
        }
    if len(matches) > 1:
        return {
            "state": "ambiguous",
            "canonical_taxon_id": None,
            "candidate_ids": sorted(candidate.taxon_id for candidate in matches),
        }
    return {"state": "unmatched", "canonical_taxon_id": None, "candidate_ids": []}


def _decorate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    support = contradiction = unknown = missing = 0
    support_weight = contradiction_weight = unknown_weight = missing_weight = 0.0
    for explanation in candidate["explanations"]:
        status = explanation["status"]
        weight = float(explanation["effective_weight"])
        similarity = explanation["similarity"]
        if status == "ignored_unknown_observation":
            unknown += 1
            unknown_weight += weight
        elif status == "candidate_state_missing":
            missing += 1
            missing_weight += weight
        elif similarity is not None and similarity > 0:
            support += 1
            support_weight += weight * float(similarity)
            if float(similarity) < 1:
                contradiction += 1
                contradiction_weight += weight * (1 - float(similarity))
        else:
            contradiction += 1
            contradiction_weight += weight
    possible = max(float(candidate["possible_weight"]), 0.0)
    compared = max(float(candidate["compared_weight"]), 0.0)
    lower = support_weight / possible if possible else 0.0
    unresolved = max(possible - compared, 0.0) + unknown_weight + missing_weight
    upper = min(1.0, (support_weight + unresolved) / possible) if possible else 0.0
    return {
        **candidate,
        "support_count": support,
        "contradiction_count": contradiction,
        "unknown_count": unknown,
        "missing_data_count": missing,
        "support_weight": round(support_weight, 6),
        "contradiction_weight": round(contradiction_weight, 6),
        "unknown_weight": round(unknown_weight, 6),
        "missing_data_weight": round(missing_weight, 6),
        "confidence_lower": round(max(0.0, min(1.0, lower)), 6),
        "confidence_upper": round(max(lower, upper), 6),
    }


def create_identification_session(
    *,
    registry_id: str,
    version: str,
    observations: list[dict[str, Any]],
    limit: int = 20,
    registry_root: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    registry_id = _safe(registry_id, "registry_id")
    version = _safe(version, "version")
    record = get_registry_version(registry_id, version, root=registry_root)
    characters = {item["character"] for item in record["characters"]}
    parsed: list[Observation] = []
    seen: set[str] = set()
    for item in observations:
        character = str(item.get("character", "")).strip()
        if character not in characters:
            raise ValueError(f"unknown matrix character: {character}")
        if character in seen:
            raise ValueError(f"duplicate observation: {character}")
        seen.add(character)
        certainty = str(item.get("certainty", "certain")).strip()
        if certainty not in {"certain", "probable", "uncertain", "unknown"}:
            raise ValueError(f"invalid certainty: {certainty}")
        weight = float(item.get("weight", 1.0))
        if weight < 0 or weight > 100:
            raise ValueError("observation weight must be between 0 and 100")
        parsed.append(
            Observation(
                character=character,
                value=item.get("value"),
                certainty=certainty,
                weight=weight,
            )
        )
    if not parsed:
        raise ValueError("at least one observation is required")
    candidates = candidates_from_registry(record)
    ranked = rank_candidates(parsed, candidates, limit=limit)
    decorated = [_decorate_candidate(item) for item in ranked["candidates"]]
    payload = {
        "schema_version": OPERATIONAL_SCHEMA_VERSION,
        "registry_id": registry_id,
        "version": version,
        "registry_checksum_sha256": record["checksum_sha256"],
        "observations": [
            {
                "character": item.character,
                "value": item.value,
                "certainty": item.certainty,
                "weight": item.weight,
            }
            for item in parsed
        ],
        "limit": limit,
    }
    replay_sha = _sha(_stable_json(payload).encode("utf-8"))
    session_id = f"matrix-session-{replay_sha[:20]}"
    result = {
        **payload,
        "session_id": session_id,
        "replay_sha256": replay_sha,
        "candidates": decorated,
        "disclaimer": ranked["disclaimer"],
        "definitive_identification": False,
        "human_review_required": True,
        "taxonomy_activation_authorized": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    destination = (root or session_root()) / f"{session_id}.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing != result:
            raise RuntimeError("immutable Matrix session conflict")
        return {"created": False, "session": existing}
    _atomic_json(destination, result)
    return {"created": True, "session": result}


def get_identification_session(session_id: str, *, root: Path | None = None) -> dict[str, Any]:
    session_id = _safe(session_id, "session_id")
    path = (root or session_root()) / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Matrix session not found: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_candidate_explanation(
    session_id: str,
    canonical_taxon_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    session = get_identification_session(session_id, root=root)
    for candidate in session["candidates"]:
        if candidate["taxon_id"] == canonical_taxon_id:
            return {
                "session_id": session_id,
                "candidate": candidate,
                "definitive_identification": False,
                "human_review_required": True,
            }
    raise FileNotFoundError(f"candidate not ranked: {canonical_taxon_id}")
