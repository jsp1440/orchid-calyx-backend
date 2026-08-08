"""Governed, non-live AI.Vision intake and Matrix handoff for CALYX issue #450."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)
from app.multimodal_intelligence.contracts import (
    CharacterObservation,
    ImageAnalysisResult,
    ModelProvenance,
    PlantPartDetection,
)
from app.multimodal_intelligence.engine import matrix_observations_from_vision
from runtime.matrix_operational import create_identification_session

VISION_SCHEMA_VERSION = "ai-vision-governed/v1"
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_LICENSES = {
    "cc0-1.0",
    "cc-by-4.0",
    "cc-by-sa-4.0",
    "cc-by-3.0",
    "cc-by-sa-3.0",
    "public-domain",
}
LICENSE_ALIASES = {
    "cc0": "cc0-1.0",
    "cc0 1.0": "cc0-1.0",
    "cc by 4.0": "cc-by-4.0",
    "cc-by 4.0": "cc-by-4.0",
    "cc by-sa 4.0": "cc-by-sa-4.0",
    "cc-by-sa 4.0": "cc-by-sa-4.0",
    "cc by 3.0": "cc-by-3.0",
    "cc by-sa 3.0": "cc-by-sa-3.0",
    "public domain": "public-domain",
    "pd": "public-domain",
}


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


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _license(value: str) -> str:
    normalized = _text(value).casefold()
    normalized = LICENSE_ALIASES.get(normalized, normalized.replace("_", "-"))
    if normalized not in ALLOWED_LICENSES:
        raise ValueError(f"VISION_LICENSE_NOT_ALLOWED:{value}")
    return normalized


def _http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("VISION_SOURCE_URL_INVALID")
    return value


def _certainty(confidence: float) -> str:
    if confidence >= 0.85:
        return "certain"
    if confidence >= 0.60:
        return "probable"
    if confidence > 0:
        return "uncertain"
    return "unknown"


def vision_root() -> Path:
    return Path(os.getenv("CALYX_AI_VISION_DIR", "/tmp/calyx/ai-vision"))


class GovernedVisionService:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        registry: ImmutableArtifactRegistry | None = None,
    ) -> None:
        self.workspace = workspace or vision_root()
        self.registry = registry or ImmutableArtifactRegistry()

    def _analysis_path(self, analysis_id: str) -> Path:
        if not analysis_id or SAFE_ID_RE.sub("_", analysis_id) != analysis_id:
            raise ValueError("VISION_ANALYSIS_ID_INVALID")
        return self.workspace / "analyses" / f"{analysis_id}.json"

    def submit_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        image = dict(payload.get("image") or {})
        model = dict(payload.get("model") or {})
        prompt = dict(payload.get("prompt") or {})
        taxon = dict(payload.get("taxon_resolution") or {})
        parts = list(payload.get("detected_parts") or [])
        observations = list(payload.get("character_observations") or [])

        image_id = _text(image.get("image_id"))
        checksum = _text(image.get("sha256")).casefold()
        source_url = _http_url(_text(image.get("source_url")))
        license_code = _license(_text(image.get("license")))
        creator = _text(image.get("creator"))
        attribution = _text(image.get("attribution"))
        acquired_at = _text(image.get("acquired_at"))
        if not image_id:
            raise ValueError("VISION_IMAGE_ID_REQUIRED")
        if not SHA256_RE.fullmatch(checksum):
            raise ValueError("VISION_IMAGE_SHA256_INVALID")
        if not creator or not attribution:
            raise ValueError("VISION_ATTRIBUTION_REQUIRED")
        if not acquired_at:
            raise ValueError("VISION_ACQUISITION_TIME_REQUIRED")

        model_provenance = ModelProvenance(
            provider=_text(model.get("provider")),
            model_name=_text(model.get("model_name")),
            model_version=_text(model.get("model_version")),
            inference_id=_text(model.get("inference_id")),
        )
        model_provenance.validate()
        prompt_id = _text(prompt.get("prompt_id"))
        prompt_version = _text(prompt.get("prompt_version"))
        prompt_sha256 = _text(prompt.get("prompt_sha256")).casefold()
        if not prompt_id or not prompt_version or not SHA256_RE.fullmatch(prompt_sha256):
            raise ValueError("VISION_PROMPT_PROVENANCE_REQUIRED")

        canonical_taxon_id = _text(taxon.get("canonical_taxon_id")) or None
        taxon_state = _text(taxon.get("state")) or "unresolved"
        if taxon_state not in {"matched", "ambiguous", "unmatched", "unresolved"}:
            raise ValueError("VISION_TAXON_RESOLUTION_STATE_INVALID")
        if taxon_state == "matched" and canonical_taxon_id is None:
            raise ValueError("VISION_MATCHED_TAXON_ID_REQUIRED")

        detected_parts = tuple(
            PlantPartDetection(part=_text(item.get("part")), confidence=float(item.get("confidence", -1)))
            for item in parts
        )
        character_observations = tuple(
            CharacterObservation(
                character_id=_text(item.get("character_id")),
                state=_text(item.get("state")) or None,
                confidence=float(item.get("confidence", -1)),
                provenance=tuple(str(v) for v in item.get("provenance", []) if str(v).strip()),
            )
            for item in observations
        )
        analysis = ImageAnalysisResult(
            image_id=image_id,
            content_hash=checksum,
            license_code=license_code,
            attribution=attribution,
            model=model_provenance,
            detected_parts=detected_parts,
            character_observations=character_observations,
            warnings=tuple(str(v) for v in payload.get("warnings", []) if str(v).strip()),
        )
        analysis.validate()
        converted = matrix_observations_from_vision(analysis)

        canonical = {
            "schema_version": VISION_SCHEMA_VERSION,
            "image": {
                "image_id": image_id,
                "sha256": checksum,
                "source_url": source_url,
                "license": license_code,
                "creator": creator,
                "attribution": attribution,
                "acquired_at": acquired_at,
            },
            "taxon_resolution": {
                "state": taxon_state,
                "canonical_taxon_id": canonical_taxon_id,
                "candidate_ids": sorted({_text(v) for v in taxon.get("candidate_ids", []) if _text(v)}),
            },
            "model": asdict(model_provenance),
            "prompt": {
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "prompt_sha256": prompt_sha256,
            },
            "detected_parts": [asdict(item) for item in detected_parts],
            "character_observations": [asdict(item) for item in character_observations],
            "matrix_observations": [asdict(item) for item in converted],
            "warnings": list(analysis.warnings),
            "corrections": [],
            "review_state": "human_review_required",
            "live_provider_call": False,
            "face_or_person_analysis": False,
            "autonomous_species_identification": False,
            "taxonomy_activation_authorized": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        digest = _sha(_stable_json(canonical).encode("utf-8"))
        analysis_id = f"vision-{digest[:20]}"
        record = {**canonical, "analysis_id": analysis_id, "replay_sha256": digest}
        path = self._analysis_path(analysis_id)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise RuntimeError("VISION_IMMUTABLE_ANALYSIS_CONFLICT")
            return {"created": False, "analysis": existing}

        artifact_id = f"vision-analysis:{analysis_id}"
        self.registry.register(
            ArtifactRegistration(
                artifact_id=artifact_id,
                content=_stable_json(record).encode("utf-8"),
                media_type="application/json",
                source_uri=source_url,
                producer_assignment_id=f"calyx-450:{analysis_id}",
                license=license_code,
                evidence_uris=(source_url,),
                metadata={"image_sha256": checksum, "model": model_provenance.model_name},
            )
        )
        self.registry.require_evidence(artifact_id)
        record["artifact_id"] = artifact_id
        _atomic_json(path, record)
        return {"created": True, "analysis": record}

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        path = self._analysis_path(analysis_id)
        if not path.exists():
            raise FileNotFoundError(f"vision analysis not found: {analysis_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def correct_observation(
        self,
        analysis_id: str,
        *,
        character_id: str,
        corrected_state: str | None,
        reviewer: str,
        rationale: str,
        reviewed_at: str,
    ) -> dict[str, Any]:
        record = self.get_analysis(analysis_id)
        character_id = _text(character_id)
        reviewer = _text(reviewer)
        rationale = _text(rationale)
        reviewed_at = _text(reviewed_at)
        if not character_id or not reviewer or not rationale or not reviewed_at:
            raise ValueError("VISION_CORRECTION_PROVENANCE_REQUIRED")
        matches = [item for item in record["character_observations"] if item["character_id"] == character_id]
        if len(matches) != 1:
            raise ValueError("VISION_CORRECTION_CHARACTER_NOT_UNIQUE")
        correction = {
            "character_id": character_id,
            "original_state": matches[0]["state"],
            "corrected_state": _text(corrected_state) or None,
            "reviewer": reviewer,
            "rationale": rationale,
            "reviewed_at": reviewed_at,
        }
        corrections = list(record.get("corrections", []))
        if correction not in corrections:
            corrections.append(correction)
        record["corrections"] = corrections
        record["review_state"] = "corrected_review_required"
        _atomic_json(self._analysis_path(analysis_id), record)
        return record

    def matrix_handoff(
        self,
        analysis_id: str,
        *,
        registry_id: str,
        version: str,
        registry_root: Path | None = None,
        session_root: Path | None = None,
    ) -> dict[str, Any]:
        record = self.get_analysis(analysis_id)
        corrected = {
            item["character_id"]: item["corrected_state"]
            for item in record.get("corrections", [])
        }
        observations = []
        for item in record["matrix_observations"]:
            confidence = float(item["confidence"])
            state = corrected.get(item["character_id"], item["state"])
            observations.append(
                {
                    "character": item["character_id"],
                    "value": state,
                    "certainty": _certainty(confidence),
                    "weight": confidence,
                }
            )
        if not observations:
            raise ValueError("VISION_MATRIX_OBSERVATIONS_REQUIRED")
        session = create_identification_session(
            registry_id=registry_id,
            version=version,
            observations=observations,
            registry_root=registry_root,
            root=session_root,
        )
        return {
            "analysis_id": analysis_id,
            "matrix_session": session,
            "observation_count": len(observations),
            "human_review_required": True,
            "autonomous_species_identification": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
