"""Versioned cultivation guidance with explicit evidence/anecdote/local-adaptation provenance."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "calyx-cultivation-guidance/v1"
SOURCE_KINDS = {"literature_evidence", "grower_observation", "local_adaptation"}
REVIEW_STATES = {"candidate", "needs_review", "accepted_as_guidance", "rejected"}
GUIDANCE_FIELDS = (
    "temperature",
    "light",
    "water",
    "humidity",
    "ventilation",
    "rest",
    "media",
    "mounting",
    "fertilization",
    "repotting",
)


def cultivation_root() -> Path:
    return Path(os.environ.get("CALYX_CULTIVATION_WORKSPACE", "/tmp/calyx/cultivation-guidance"))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_id(value: object, code: str) -> str:
    item = _text(value)
    if not item or item in {".", ".."} or "/" in item or "\\" in item or "\x00" in item:
        raise ValueError(code)
    return item


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("CULTIVATION_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode("utf-8")).hexdigest()[:20]


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


class CultivationGuidanceService:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace or cultivation_root()

    def _root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / _owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return payload

    def register_guidance(self, owner_id: str, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        guidance_id = _safe_id(payload.get("guidance_id"), "CULTIVATION_GUIDANCE_ID_INVALID")
        version = int(payload.get("version", 1))
        if version < 1:
            raise ValueError("CULTIVATION_VERSION_INVALID")
        identity = dict(payload.get("identity") or {})
        if not _text(identity.get("canonical_taxon_id") or identity.get("hybrid_identity")):
            raise ValueError("CULTIVATION_IDENTITY_REQUIRED")
        source_kind = _text(payload.get("source_kind"))
        if source_kind not in SOURCE_KINDS:
            raise ValueError("CULTIVATION_SOURCE_KIND_INVALID")
        source = dict(payload.get("source") or {})
        if source_kind == "literature_evidence" and not _text(source.get("uri")):
            raise ValueError("CULTIVATION_EVIDENCE_SOURCE_REQUIRED")
        locality = dict(payload.get("locality_context") or {})
        confidence = float(payload.get("confidence", 0.0))
        if confidence < 0 or confidence > 1:
            raise ValueError("CULTIVATION_CONFIDENCE_INVALID")
        guidance = {name: payload.get(name) for name in GUIDANCE_FIELDS if payload.get(name) not in (None, "", [], {})}
        if not guidance:
            raise ValueError("CULTIVATION_GUIDANCE_CONTENT_REQUIRED")
        review_state = _text(payload.get("review_state")) or "candidate"
        if review_state not in REVIEW_STATES:
            raise ValueError("CULTIVATION_REVIEW_STATE_INVALID")
        record = {
            "schema_version": SCHEMA_VERSION,
            "guidance_id": guidance_id,
            "version": version,
            "identity": identity,
            "guidance": guidance,
            "source_kind": source_kind,
            "source": source,
            "grower_observation": dict(payload.get("grower_observation") or {}),
            "locality_context": locality,
            "confidence": confidence,
            "contradictions": list(payload.get("contradictions") or []),
            "review_state": review_state,
            "evidence_backed": source_kind == "literature_evidence",
            "anecdotal": source_kind == "grower_observation",
            "local_adaptation": source_kind == "local_adaptation",
            "pesticide_advice_authorized": False,
            "medical_advice_authorized": False,
            "autonomous_greenhouse_control_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "created_by": _text(actor),
            "created_at": _now(),
        }
        record["record_digest"] = _digest(record)
        path = self._root(owner_id) / "guidance" / guidance_id / f"v{version}.json"
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("CULTIVATION_IMMUTABLE_VERSION_CONFLICT")
            return existing
        return self._write(path, record)

    def review_guidance(self, owner_id: str, guidance_id: str, version: int, *, state: str, reviewer: str, rationale: str) -> dict[str, Any]:
        if state not in REVIEW_STATES:
            raise ValueError("CULTIVATION_REVIEW_STATE_INVALID")
        if not _text(reviewer) or not _text(rationale):
            raise ValueError("CULTIVATION_REVIEW_FIELDS_REQUIRED")
        source = self._read(self._root(owner_id) / "guidance" / _safe_id(guidance_id, "CULTIVATION_GUIDANCE_ID_INVALID") / f"v{int(version)}.json")
        decision = {
            "guidance_id": source["guidance_id"],
            "version": source["version"],
            "state": state,
            "reviewer": reviewer,
            "rationale": rationale,
            "reviewed_at": _now(),
            "source_digest": source["record_digest"],
        }
        decision["decision_digest"] = _digest(decision)
        return self._write(self._root(owner_id) / "reviews" / f"{source['guidance_id']}-v{source['version']}.json", decision)

    def _all_records(self, owner_id: str) -> list[dict[str, Any]]:
        base = self._root(owner_id) / "guidance"
        return [self._read(path) for path in sorted(base.glob("*/v*.json"))] if base.exists() else []

    def assemble_profile(self, owner_id: str, identity_key: str) -> dict[str, Any]:
        key = _text(identity_key)
        if not key:
            raise ValueError("CULTIVATION_IDENTITY_REQUIRED")
        records = [
            item for item in self._all_records(owner_id)
            if key in {_text(item["identity"].get("canonical_taxon_id")), _text(item["identity"].get("hybrid_identity"))}
        ]
        if not records:
            raise LookupError("CULTIVATION_GUIDANCE_NOT_FOUND")
        grouped = {kind: [] for kind in sorted(SOURCE_KINDS)}
        for item in records:
            grouped[item["source_kind"]].append(item)
        contradictions: list[dict[str, Any]] = []
        for field in GUIDANCE_FIELDS:
            values: dict[str, set[str]] = {}
            for item in records:
                if field in item["guidance"]:
                    values.setdefault(item["source_kind"], set()).add(_stable(item["guidance"][field]))
            flattened = {value for bucket in values.values() for value in bucket}
            if len(flattened) > 1:
                contradictions.append({"field": field, "source_kinds": sorted(values), "state": "review_required"})
        return {
            "schema_version": SCHEMA_VERSION,
            "identity_key": key,
            "evidence_backed_guidance": grouped["literature_evidence"],
            "grower_observations": grouped["grower_observation"],
            "local_adaptations": grouped["local_adaptation"],
            "contradictions": contradictions,
            "contradiction_count": len(contradictions),
            "evidence_anecdote_separation": True,
            "pesticide_advice_authorized": False,
            "medical_advice_authorized": False,
            "autonomous_greenhouse_control_authorized": False,
            "scientific_publication_authorized": False,
        }

    def conservatory_oasis_handoff(self, owner_id: str, identity_key: str) -> dict[str, Any]:
        profile = self.assemble_profile(owner_id, identity_key)
        return {
            "schema_version": SCHEMA_VERSION,
            "identity_key": identity_key,
            "guidance_profile": profile,
            "handoff_targets": ["Conservatory", "OASIS"],
            "decision_support_only": True,
            "autonomous_greenhouse_control_authorized": False,
            "pesticide_advice_authorized": False,
            "medical_advice_authorized": False,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        records = self._all_records(owner_id)
        evidence = sum(1 for item in records if item["source_kind"] == "literature_evidence")
        anecdote = sum(1 for item in records if item["source_kind"] == "grower_observation")
        local = sum(1 for item in records if item["source_kind"] == "local_adaptation")
        return {
            "schema_version": SCHEMA_VERSION,
            "guidance_record_count": len(records),
            "literature_evidence_count": evidence,
            "grower_observation_count": anecdote,
            "local_adaptation_count": local,
            "evidence_anecdote_separation": True,
            "pesticide_advice_authorized": False,
            "medical_advice_authorized": False,
            "autonomous_greenhouse_control_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "deployment_authorized": False,
        }
