"""Governed pollinator and ecological-interaction evidence pipeline for CALYX #464.

Records are evidence-first and review-only. The service never infers undocumented
pollination, publishes scientific conclusions, or mutates the production graph.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.taxonomy_preflight import scientific_name, taxon_key

SCHEMA_VERSION = "calyx-ecological-interactions/v1"
INTERACTION_TYPES = {
    "pollinates",
    "visits_flower",
    "herbivory",
    "mycorrhizal_association",
    "epiphyte_on",
    "predation",
    "seed_dispersal",
    "other_documented_interaction",
}


def interaction_root() -> Path:
    return Path(os.environ.get("CALYX_INTERACTION_WORKSPACE", "/tmp/calyx/interactions"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("INTERACTION_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class EvidenceSpan:
    evidence_id: str
    source_id: str
    source_url: str
    exact_text: str
    locator: str
    retrieved_at: str


@dataclass(frozen=True)
class InteractionRecord:
    interaction_id: str
    subject_taxon_key: str
    subject_scientific_name: str
    interaction_type: str
    organism_identity: str
    organism_taxon_key: str | None
    locality: str | None
    observed_at: str | None
    evidence: EvidenceSpan
    confidence: float
    contradiction: bool
    review_status: str
    provenance: dict[str, Any]


class EcologicalInteractionService:
    """Owner-scoped deterministic interaction workspace with bounded staging."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace or interaction_root()

    def _root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / _owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _canonical_taxon(row: dict[str, str]) -> tuple[str, str]:
        name = scientific_name(row)
        key = taxon_key(row)
        if not name or not key:
            raise ValueError("INTERACTION_SUBJECT_TAXON_UNRESOLVED")
        return key, name

    def record(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        interaction_id = _text(payload.get("interaction_id"))
        interaction_type = _text(payload.get("interaction_type")).casefold()
        if not interaction_id:
            raise ValueError("INTERACTION_ID_REQUIRED")
        if interaction_type not in INTERACTION_TYPES:
            raise ValueError("INTERACTION_TYPE_UNSUPPORTED")

        subject = payload.get("subject_taxon")
        if not isinstance(subject, dict):
            raise TypeError("INTERACTION_SUBJECT_TAXON_REQUIRED")
        subject_key, subject_name = self._canonical_taxon(subject)

        evidence_payload = payload.get("evidence")
        if not isinstance(evidence_payload, dict):
            raise TypeError("INTERACTION_EVIDENCE_REQUIRED")
        evidence = EvidenceSpan(
            evidence_id=_text(evidence_payload.get("evidence_id")),
            source_id=_text(evidence_payload.get("source_id")),
            source_url=_text(evidence_payload.get("source_url")),
            exact_text=_text(evidence_payload.get("exact_text")),
            locator=_text(evidence_payload.get("locator")),
            retrieved_at=_text(evidence_payload.get("retrieved_at")),
        )
        if not all((evidence.evidence_id, evidence.source_id, evidence.source_url, evidence.exact_text, evidence.locator, evidence.retrieved_at)):
            raise ValueError("INTERACTION_EVIDENCE_SPAN_INCOMPLETE")

        confidence = float(payload.get("confidence", 0))
        if not 0 <= confidence <= 1:
            raise ValueError("INTERACTION_CONFIDENCE_INVALID")

        organism_identity = _text(payload.get("organism_identity"))
        candidates = payload.get("organism_taxon_candidates") or []
        if not organism_identity:
            raise ValueError("INTERACTION_ORGANISM_IDENTITY_REQUIRED")
        if not isinstance(candidates, list):
            raise TypeError("INTERACTION_ORGANISM_CANDIDATES_INVALID")

        organism_key: str | None = None
        review_reasons: list[str] = []
        if len(candidates) == 1:
            candidate = candidates[0]
            if not isinstance(candidate, dict):
                raise TypeError("INTERACTION_ORGANISM_CANDIDATE_INVALID")
            try:
                organism_key, _ = self._canonical_taxon(candidate)
            except ValueError:
                review_reasons.append("organism_taxon_unresolved")
        elif len(candidates) > 1:
            review_reasons.append("organism_taxon_ambiguous")
        else:
            review_reasons.append("organism_taxon_not_supplied")

        contradiction = bool(payload.get("contradiction", False))
        if contradiction:
            review_reasons.append("contradictory_evidence")
        if confidence < 0.7:
            review_reasons.append("low_confidence")
        if interaction_type == "pollinates" and not bool(payload.get("pollination_documented", False)):
            raise ValueError("INTERACTION_POLLINATION_DOCUMENTATION_REQUIRED")

        review_status = "review_required" if review_reasons else "candidate_ready"
        record = InteractionRecord(
            interaction_id=interaction_id,
            subject_taxon_key=subject_key,
            subject_scientific_name=subject_name,
            interaction_type=interaction_type,
            organism_identity=organism_identity,
            organism_taxon_key=organism_key,
            locality=_text(payload.get("locality")) or None,
            observed_at=_text(payload.get("observed_at")) or None,
            evidence=evidence,
            confidence=confidence,
            contradiction=contradiction,
            review_status=review_status,
            provenance={
                "source_url": evidence.source_url,
                "source_id": evidence.source_id,
                "evidence_id": evidence.evidence_id,
                "retrieved_at": evidence.retrieved_at,
                "literature_binding_required": True,
                "production_graph_mutation_authorized": False,
                "scientific_publication_authorized": False,
            },
        )
        stored = {**asdict(record), "review_reasons": sorted(set(review_reasons))}
        stored["record_digest"] = _digest(stored)
        return self._write(self._root(owner_id) / "records" / f"{interaction_id}.json", stored)

    def get(self, owner_id: str, interaction_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "records" / f"{interaction_id}.json")

    def review_queue(self, owner_id: str) -> dict[str, Any]:
        directory = self._root(owner_id) / "records"
        records = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                item = self._read(path)
                if item["review_status"] == "review_required":
                    records.append(item)
        return {"schema_version": SCHEMA_VERSION, "records": records, "count": len(records)}

    def stage(self, owner_id: str, *, limit: int = 100) -> dict[str, Any]:
        if limit < 1 or limit > 5000:
            raise ValueError("INTERACTION_STAGE_LIMIT_INVALID")
        directory = self._root(owner_id) / "records"
        candidates = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                item = self._read(path)
                if item["review_status"] == "candidate_ready":
                    candidates.append(item)
        selected = candidates[:limit]
        staging_path = self._root(owner_id) / "staging" / "relationships.json"
        current = {"relationships": []}
        if staging_path.exists():
            current = self._read(staging_path)
        existing = {item["record_digest"] for item in current.get("relationships", [])}
        additions = [item for item in selected if item["record_digest"] not in existing]
        merged = current.get("relationships", []) + additions
        self._write(staging_path, {"schema_version": SCHEMA_VERSION, "relationships": merged})
        return {
            "schema_version": SCHEMA_VERSION,
            "examined": len(selected),
            "added": len(additions),
            "already_staged": len(selected) - len(additions),
            "total_staged": len(merged),
            "bounded": True,
            "production_graph_mutation_performed": False,
            "relationship_provenance_preserved": True,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        directory = self._root(owner_id) / "records"
        all_records = [self._read(path) for path in sorted(directory.glob("*.json"))] if directory.exists() else []
        review = [item for item in all_records if item["review_status"] == "review_required"]
        ready = [item for item in all_records if item["review_status"] == "candidate_ready"]
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": "REVIEW_READY" if ready else "NO_CANDIDATE_RELATIONSHIPS",
            "record_count": len(all_records),
            "candidate_ready_count": len(ready),
            "review_required_count": len(review),
            "literature_evidence_binding_required": True,
            "undocumented_pollination_inference_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "production_deployment_authorized": False,
        }
