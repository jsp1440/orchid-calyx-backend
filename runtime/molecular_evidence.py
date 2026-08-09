"""Governed molecular, voucher, accession, and phylogenetic evidence foundation.

Records molecular evidence and review state without harvesting sequences, asserting
phylogenetic truth, publishing scientific claims, or mutating the production graph.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import ArtifactRegistration, ImmutableArtifactRegistry

SCHEMA_VERSION = "calyx-molecular-evidence/v1"
REVIEW_STATES = {"candidate", "needs_review", "accepted_as_evidence", "rejected"}
CLAIM_STATES = {"candidate", "needs_review", "accepted_as_evidence", "rejected"}


def molecular_root() -> Path:
    return Path(os.environ.get("CALYX_MOLECULAR_WORKSPACE", "/tmp/calyx/molecular-evidence"))


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
        raise ValueError("MOLECULAR_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode("utf-8")).hexdigest()[:20]


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


class MolecularEvidenceService:
    def __init__(self, workspace: Path | None = None, *, artifacts: ImmutableArtifactRegistry | None = None) -> None:
        self.workspace = workspace or molecular_root()
        self.artifacts = artifacts or ImmutableArtifactRegistry()

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

    def register_sequence_evidence(self, owner_id: str, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        evidence_id = _safe_id(payload.get("evidence_id"), "MOLECULAR_EVIDENCE_ID_INVALID")
        accession = _text(payload.get("accession"))
        marker = _text(payload.get("marker"))
        source_database = _text(payload.get("source_database"))
        specimen_provenance = dict(payload.get("specimen_provenance") or {})
        voucher = dict(payload.get("voucher") or {})
        if not accession or not marker or not source_database:
            raise ValueError("MOLECULAR_SEQUENCE_IDENTITY_REQUIRED")
        if not specimen_provenance:
            raise ValueError("MOLECULAR_SPECIMEN_PROVENANCE_REQUIRED")

        canonical_taxon_id = _text(payload.get("canonical_taxon_id")) or None
        accepted_name = _text(payload.get("accepted_name")) or None
        submitted_name = _text(payload.get("submitted_name")) or None
        resolution_state = "resolved" if canonical_taxon_id and accepted_name else "ambiguous_or_unresolved"
        confidence = float(payload.get("confidence", 0.0))
        if not 0 <= confidence <= 1:
            raise ValueError("MOLECULAR_CONFIDENCE_INVALID")
        evidence_span = dict(payload.get("evidence_span") or {})
        if not evidence_span.get("source_uri") or evidence_span.get("start") is None or evidence_span.get("end") is None:
            raise ValueError("MOLECULAR_EVIDENCE_SPAN_REQUIRED")
        if int(evidence_span["start"]) < 0 or int(evidence_span["end"]) <= int(evidence_span["start"]):
            raise ValueError("MOLECULAR_EVIDENCE_SPAN_INVALID")

        record = {
            "schema_version": SCHEMA_VERSION,
            "evidence_id": evidence_id,
            "accession": accession,
            "marker": marker,
            "source_database": source_database,
            "voucher": voucher,
            "specimen_provenance": specimen_provenance,
            "submitted_name": submitted_name,
            "canonical_taxon_id": canonical_taxon_id,
            "accepted_name": accepted_name,
            "taxon_resolution_state": resolution_state,
            "evidence_span": evidence_span,
            "confidence": confidence,
            "conflicts": list(payload.get("conflicts") or []),
            "review_state": "needs_review" if resolution_state != "resolved" or payload.get("conflicts") else "candidate",
            "alignment_or_analysis_artifact_ids": [],
            "phylogenetic_claim_ids": [],
            "live_sequence_harvesting_authorized": False,
            "phylogenetic_truth_claim_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "created_by": _text(actor),
            "created_at": _now(),
        }
        record["record_digest"] = _digest(record)
        return self._write(self._root(owner_id) / "evidence" / f"{evidence_id}.json", record)

    def get_evidence(self, owner_id: str, evidence_id: str) -> dict[str, Any]:
        safe_id = _safe_id(evidence_id, "MOLECULAR_EVIDENCE_ID_INVALID")
        return self._read(self._root(owner_id) / "evidence" / f"{safe_id}.json")

    def register_analysis_artifact(self, owner_id: str, evidence_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        evidence = self.get_evidence(owner_id, evidence_id)
        artifact_id = _safe_id(payload.get("artifact_id"), "MOLECULAR_ARTIFACT_ID_INVALID")
        analysis_type = _text(payload.get("analysis_type"))
        content = _text(payload.get("content"))
        if not analysis_type or not content:
            raise ValueError("MOLECULAR_ANALYSIS_ARTIFACT_REQUIRED")
        source_uri = _text(payload.get("source_uri")) or f"calyx://molecular/evidence/{evidence_id}/analysis/{artifact_id}"
        evidence_uris = tuple(_text(item) for item in payload.get("evidence_uris", []) if _text(item)) or (
            str(evidence["evidence_span"]["source_uri"]),
        )
        result = self.artifacts.register(
            ArtifactRegistration(
                artifact_id=f"molecular-analysis:{artifact_id}",
                content=content.encode("utf-8"),
                media_type=_text(payload.get("media_type")) or "application/json",
                source_uri=source_uri,
                producer_assignment_id="CALYX-477-molecular-evidence",
                evidence_uris=evidence_uris,
                metadata={
                    "analysis_type": analysis_type,
                    "evidence_id": evidence_id,
                    "publication_authorized": False,
                },
            )
        )
        record = {
            "artifact_id": result.record.artifact_id,
            "checksum": result.record.checksum,
            "analysis_type": analysis_type,
            "created": result.created,
            "publication_authorized": False,
        }
        path = self._root(owner_id) / "evidence" / f"{evidence_id}.json"
        evidence["alignment_or_analysis_artifact_ids"] = sorted(
            set(evidence.get("alignment_or_analysis_artifact_ids") or []) | {record["artifact_id"]}
        )
        evidence["updated_at"] = _now()
        self._write(path, evidence)
        return record

    def record_phylogenetic_claim(self, owner_id: str, evidence_id: str, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        evidence = self.get_evidence(owner_id, evidence_id)
        claim_id = _safe_id(payload.get("claim_id"), "PHYLOGENETIC_CLAIM_ID_INVALID")
        statement = _text(payload.get("statement"))
        claim_type = _text(payload.get("claim_type"))
        if not statement or not claim_type:
            raise ValueError("PHYLOGENETIC_CLAIM_REQUIRED")
        evidence_span = dict(payload.get("evidence_span") or evidence["evidence_span"])
        if not evidence_span.get("source_uri"):
            raise ValueError("PHYLOGENETIC_CLAIM_EVIDENCE_REQUIRED")
        confidence = float(payload.get("confidence", evidence.get("confidence", 0.0)))
        if not 0 <= confidence <= 1:
            raise ValueError("PHYLOGENETIC_CLAIM_CONFIDENCE_INVALID")
        analysis_artifact_ids = sorted({_text(x) for x in payload.get("analysis_artifact_ids", []) if _text(x)})
        bound_artifacts = set(evidence.get("alignment_or_analysis_artifact_ids") or [])
        if any(artifact_id not in bound_artifacts for artifact_id in analysis_artifact_ids):
            raise ValueError("PHYLOGENETIC_ANALYSIS_ARTIFACT_NOT_BOUND")
        claim = {
            "schema_version": SCHEMA_VERSION,
            "claim_id": claim_id,
            "evidence_id": evidence_id,
            "claim_type": claim_type,
            "statement": statement,
            "evidence_span": evidence_span,
            "analysis_artifact_ids": analysis_artifact_ids,
            "confidence": confidence,
            "conflicts": list(payload.get("conflicts") or []),
            "review_state": "needs_review",
            "truth_status": "not_asserted",
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "created_by": _text(actor),
            "created_at": _now(),
        }
        claim["claim_digest"] = _digest(claim)
        self._write(self._root(owner_id) / "claims" / f"{claim_id}.json", claim)
        evidence["phylogenetic_claim_ids"] = sorted(set(evidence.get("phylogenetic_claim_ids") or []) | {claim_id})
        evidence["updated_at"] = _now()
        self._write(self._root(owner_id) / "evidence" / f"{evidence_id}.json", evidence)
        return claim

    def review_evidence(self, owner_id: str, evidence_id: str, *, state: str, reviewer: str, rationale: str) -> dict[str, Any]:
        if state not in REVIEW_STATES:
            raise ValueError("MOLECULAR_REVIEW_STATE_INVALID")
        if not _text(reviewer) or not _text(rationale):
            raise ValueError("MOLECULAR_REVIEW_FIELDS_REQUIRED")
        path = self._root(owner_id) / "evidence" / f"{_safe_id(evidence_id, 'MOLECULAR_EVIDENCE_ID_INVALID')}.json"
        record = self._read(path)
        if state == "accepted_as_evidence" and record["taxon_resolution_state"] != "resolved":
            raise ValueError("MOLECULAR_TAXON_RESOLUTION_REQUIRED")
        history = list(record.get("review_history") or [])
        history.append({"from": record["review_state"], "to": state, "reviewer": reviewer, "rationale": rationale, "at": _now()})
        record["review_state"] = state
        record["review_history"] = history
        record["updated_at"] = _now()
        return self._write(path, record)

    def review_claim(self, owner_id: str, claim_id: str, *, state: str, reviewer: str, rationale: str) -> dict[str, Any]:
        if state not in CLAIM_STATES:
            raise ValueError("PHYLOGENETIC_CLAIM_REVIEW_STATE_INVALID")
        if not _text(reviewer) or not _text(rationale):
            raise ValueError("PHYLOGENETIC_CLAIM_REVIEW_FIELDS_REQUIRED")
        path = self._root(owner_id) / "claims" / f"{_safe_id(claim_id, 'PHYLOGENETIC_CLAIM_ID_INVALID')}.json"
        claim = self._read(path)
        if state == "accepted_as_evidence":
            source_evidence = self.get_evidence(owner_id, claim["evidence_id"])
            if source_evidence["review_state"] != "accepted_as_evidence":
                raise ValueError("PHYLOGENETIC_SOURCE_EVIDENCE_NOT_ACCEPTED")
            if source_evidence["taxon_resolution_state"] != "resolved":
                raise ValueError("PHYLOGENETIC_SOURCE_TAXON_UNRESOLVED")
        history = list(claim.get("review_history") or [])
        history.append({"from": claim["review_state"], "to": state, "reviewer": reviewer, "rationale": rationale, "at": _now()})
        claim["review_state"] = state
        claim["review_history"] = history
        claim["truth_status"] = "reviewed_evidence_only" if state == "accepted_as_evidence" else "not_asserted"
        claim["updated_at"] = _now()
        return self._write(path, claim)

    def ambiguity_queue(self, owner_id: str) -> dict[str, Any]:
        evidence_dir = self._root(owner_id) / "evidence"
        items = []
        if evidence_dir.exists():
            for path in sorted(evidence_dir.glob("*.json")):
                record = self._read(path)
                if record["taxon_resolution_state"] != "resolved" or record.get("conflicts"):
                    items.append({
                        "evidence_id": record["evidence_id"],
                        "accession": record["accession"],
                        "submitted_name": record.get("submitted_name"),
                        "taxon_resolution_state": record["taxon_resolution_state"],
                        "conflicts": record.get("conflicts") or [],
                        "review_state": record["review_state"],
                    })
        return {"schema_version": SCHEMA_VERSION, "items": items, "human_review_required": True}

    def readiness(self, owner_id: str) -> dict[str, Any]:
        evidence_dir = self._root(owner_id) / "evidence"
        claim_dir = self._root(owner_id) / "claims"
        evidence = [self._read(path) for path in sorted(evidence_dir.glob("*.json"))] if evidence_dir.exists() else []
        claims = [self._read(path) for path in sorted(claim_dir.glob("*.json"))] if claim_dir.exists() else []
        return {
            "schema_version": SCHEMA_VERSION,
            "evidence_count": len(evidence),
            "phylogenetic_claim_count": len(claims),
            "unresolved_taxon_evidence_ids": [item["evidence_id"] for item in evidence if item["taxon_resolution_state"] != "resolved"],
            "pending_evidence_review_ids": [item["evidence_id"] for item in evidence if item["review_state"] in {"candidate", "needs_review"}],
            "pending_claim_review_ids": [item["claim_id"] for item in claims if item["review_state"] in {"candidate", "needs_review"}],
            "ambiguity_queue_count": len(self.ambiguity_queue(owner_id)["items"]),
            "live_sequence_harvesting_authorized": False,
            "phylogenetic_truth_claim_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "deployment_authorized": False,
        }
