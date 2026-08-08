"""Review-only orchid-fungus evidence pipeline for CALYX issue #465."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from runtime.literature_acquisition import LiteratureAcquisitionService
from runtime.taxonomy_preflight import scientific_name, taxon_key

SCHEMA_VERSION = "calyx-mycorrhizal-evidence/v1"
ASSOCIATION_TYPES = {
    "mycorrhizal_association",
    "peloton_observed",
    "fungal_isolate_detected",
    "sequence_detected",
    "co_occurrence_only",
}


def mycorrhizal_root() -> Path:
    return Path(os.environ.get("CALYX_MYCORRHIZAL_WORKSPACE", "/tmp/calyx/mycorrhizal"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("MYCORRHIZA_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


class MycorrhizalEvidenceService:
    def __init__(self, workspace: Path | None = None, *, literature: LiteratureAcquisitionService | None = None) -> None:
        self.workspace = workspace or mycorrhizal_root()
        self.literature = literature or LiteratureAcquisitionService(self.workspace / "literature")

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
    def _orchid_identity(row: dict[str, str]) -> tuple[str, str]:
        name = scientific_name(row)
        key = taxon_key(row)
        if not name or key == "name:":
            raise ValueError("MYCORRHIZA_ORCHID_TAXON_UNRESOLVED")
        return key, name

    def _bind_evidence(self, run_id: str, span_id: int) -> dict[str, Any]:
        evidence = self.literature.evidence(run_id, offset=max(span_id - 1, 0), limit=1)
        items = evidence["items"]
        if not items or int(items[0]["span_id"]) != span_id:
            raise ValueError("MYCORRHIZA_EVIDENCE_SPAN_NOT_FOUND")
        readiness = self.literature.readiness(run_id)
        span = items[0]
        return {
            "literature_run_id": run_id,
            "span_id": span_id,
            "char_start": span["char_start"],
            "char_end": span["char_end"],
            "text": span["text"],
            "sha256": span["sha256"],
            "source_id": readiness["identity"]["source_id"],
            "revision_id": readiness["identity"]["revision_id"],
            "source_sha256": readiness["source_sha256"],
            "extraction_sha256": readiness["extraction_sha256"],
        }

    def record(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        association_id = _text(payload.get("association_id"))
        association_type = _text(payload.get("association_type")).casefold()
        if not association_id:
            raise ValueError("MYCORRHIZA_ASSOCIATION_ID_REQUIRED")
        if association_type not in ASSOCIATION_TYPES:
            raise ValueError("MYCORRHIZA_ASSOCIATION_TYPE_UNSUPPORTED")
        orchid = payload.get("orchid_taxon")
        if not isinstance(orchid, dict):
            raise TypeError("MYCORRHIZA_ORCHID_TAXON_REQUIRED")
        orchid_key, orchid_name = self._orchid_identity(orchid)

        fungal_name = _text(payload.get("fungal_identity"))
        fungal_candidates = payload.get("fungal_candidates") or []
        if not fungal_name:
            raise ValueError("MYCORRHIZA_FUNGAL_IDENTITY_REQUIRED")
        if not isinstance(fungal_candidates, list):
            raise TypeError("MYCORRHIZA_FUNGAL_CANDIDATES_INVALID")
        fungal_key: str | None = None
        review_reasons: list[str] = []
        if len(fungal_candidates) == 1:
            candidate = fungal_candidates[0]
            if not isinstance(candidate, dict):
                raise TypeError("MYCORRHIZA_FUNGAL_CANDIDATE_INVALID")
            candidate_name = scientific_name(candidate)
            candidate_key = taxon_key(candidate)
            if candidate_name and candidate_key != "name:":
                fungal_key = candidate_key
            else:
                review_reasons.append("fungal_identity_unresolved")
        elif len(fungal_candidates) > 1:
            review_reasons.append("fungal_identity_ambiguous")
        else:
            review_reasons.append("fungal_identity_unresolved")

        tissue = _text(payload.get("tissue"))
        life_stage = _text(payload.get("life_stage"))
        locality = _text(payload.get("locality"))
        method = _text(payload.get("method"))
        if not tissue or not life_stage or not method:
            raise ValueError("MYCORRHIZA_CONTEXT_REQUIRED")

        confidence = float(payload.get("confidence", -1))
        if not 0 <= confidence <= 1:
            raise ValueError("MYCORRHIZA_CONFIDENCE_INVALID")
        contradiction = bool(payload.get("contradiction", False))
        if confidence < 0.7:
            review_reasons.append("low_confidence")
        if contradiction:
            review_reasons.append("contradictory_evidence")

        evidence_ref = payload.get("evidence")
        if not isinstance(evidence_ref, dict):
            raise TypeError("MYCORRHIZA_EVIDENCE_REQUIRED")
        run_id = _text(evidence_ref.get("literature_run_id"))
        span_id = int(evidence_ref.get("span_id", 0))
        if not run_id or span_id < 1:
            raise ValueError("MYCORRHIZA_EVIDENCE_REFERENCE_INVALID")
        evidence = self._bind_evidence(run_id, span_id)

        documented = bool(payload.get("association_documented", False))
        if association_type == "co_occurrence_only" and documented:
            raise ValueError("MYCORRHIZA_COOCCURRENCE_CANNOT_VERIFY_SYMBIOSIS")
        if association_type == "mycorrhizal_association" and not documented:
            raise ValueError("MYCORRHIZA_ASSOCIATION_DOCUMENTATION_REQUIRED")

        review_status = "review_required" if review_reasons else "candidate_ready"
        record = {
            "schema_version": SCHEMA_VERSION,
            "association_id": association_id,
            "association_type": association_type,
            "association_documented": documented,
            "orchid_taxon_key": orchid_key,
            "orchid_scientific_name": orchid_name,
            "fungal_identity": fungal_name,
            "fungal_taxon_key": fungal_key,
            "tissue": tissue,
            "life_stage": life_stage,
            "locality": locality or None,
            "method": method,
            "evidence": evidence,
            "confidence": confidence,
            "contradiction": contradiction,
            "review_status": review_status,
            "review_reasons": sorted(set(review_reasons)),
            "provenance": {
                "association_id": association_id,
                "orchid_taxon_key": orchid_key,
                "fungal_taxon_key": fungal_key,
                "literature_run_id": run_id,
                "evidence_span_id": span_id,
                "evidence_sha256": evidence["sha256"],
                "cooccurrence_as_verified_symbiosis_authorized": False,
                "scientific_publication_authorized": False,
                "production_graph_mutation_authorized": False,
            },
        }
        record["record_digest"] = _digest(record)
        return self._write(self._root(owner_id) / "records" / f"{association_id}.json", record)

    def get(self, owner_id: str, association_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "records" / f"{association_id}.json")

    def unresolved_queue(self, owner_id: str) -> dict[str, Any]:
        directory = self._root(owner_id) / "records"
        records = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                record = self._read(path)
                if record["review_status"] == "review_required":
                    records.append(record)
        return {"schema_version": SCHEMA_VERSION, "records": records, "count": len(records)}

    def provenance(self, owner_id: str, association_id: str) -> dict[str, Any]:
        record = self.get(owner_id, association_id)
        evidence = record["evidence"]
        return {
            "schema_version": SCHEMA_VERSION,
            "association_id": association_id,
            "path": [
                {"type": "association", "id": association_id, "digest": record["record_digest"]},
                {"type": "literature_evidence_span", "id": f"{evidence['literature_run_id']}:{evidence['span_id']}", "sha256": evidence["sha256"]},
                {"type": "literature_revision", "id": evidence["revision_id"], "source_id": evidence["source_id"], "source_sha256": evidence["source_sha256"]},
            ],
        }

    def stage(self, owner_id: str, *, limit: int = 100) -> dict[str, Any]:
        if limit < 1 or limit > 5000:
            raise ValueError("MYCORRHIZA_STAGE_LIMIT_INVALID")
        directory = self._root(owner_id) / "records"
        candidates = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                record = self._read(path)
                if record["review_status"] == "candidate_ready":
                    candidates.append(record)
        selected = candidates[:limit]
        path = self._root(owner_id) / "staging" / "relationships.json"
        current = self._read(path) if path.exists() else {"relationships": []}
        existing = {item["record_digest"] for item in current["relationships"]}
        additions = [item for item in selected if item["record_digest"] not in existing]
        merged = current["relationships"] + additions
        self._write(path, {"schema_version": SCHEMA_VERSION, "relationships": merged})
        return {
            "schema_version": SCHEMA_VERSION,
            "examined": len(selected),
            "added": len(additions),
            "already_staged": len(selected) - len(additions),
            "total_staged": len(merged),
            "bounded": True,
            "production_graph_mutation_performed": False,
            "provenance_preserved": True,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        directory = self._root(owner_id) / "records"
        records = [self._read(path) for path in sorted(directory.glob("*.json"))] if directory.exists() else []
        ready = [item for item in records if item["review_status"] == "candidate_ready"]
        review = [item for item in records if item["review_status"] == "review_required"]
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": "REVIEW_READY" if ready else "NO_CANDIDATE_ASSOCIATIONS",
            "record_count": len(records),
            "candidate_ready_count": len(ready),
            "review_required_count": len(review),
            "literature_evidence_bound": True,
            "cooccurrence_as_verified_symbiosis_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "production_deployment_authorized": False,
        }
