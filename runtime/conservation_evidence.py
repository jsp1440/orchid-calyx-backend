"""Review-only conservation evidence, threat, and protection-status pipeline for CALYX #466."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from runtime.literature_acquisition import LiteratureAcquisitionService
from runtime.taxonomy_preflight import scientific_name, taxon_key

SCHEMA_VERSION = "calyx-conservation-evidence/v1"


def conservation_root() -> Path:
    return Path(os.environ.get("CALYX_CONSERVATION_WORKSPACE", "/tmp/calyx/conservation"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("CONSERVATION_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


class ConservationEvidenceService:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        literature: LiteratureAcquisitionService | None = None,
        as_of: date | None = None,
        stale_after_years: int = 5,
    ) -> None:
        self.workspace = workspace or conservation_root()
        self.literature = literature or LiteratureAcquisitionService(self.workspace / "literature")
        self.as_of = as_of or date.today()
        self.stale_after_years = stale_after_years

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
    def _taxon_identity(row: dict[str, str]) -> tuple[str, str]:
        name = scientific_name(row)
        key = taxon_key(row)
        if not name or key == "name:":
            raise ValueError("CONSERVATION_TAXON_UNRESOLVED")
        return key, name

    def _bind_evidence(self, run_id: str, span_id: int) -> dict[str, Any]:
        evidence = self.literature.evidence(run_id, offset=max(span_id - 1, 0), limit=1)
        if not evidence["items"] or int(evidence["items"][0]["span_id"]) != span_id:
            raise ValueError("CONSERVATION_EVIDENCE_SPAN_NOT_FOUND")
        span = evidence["items"][0]
        readiness = self.literature.readiness(run_id)
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

    def _freshness(self, assessment_date: str) -> dict[str, Any]:
        try:
            assessed = date.fromisoformat(assessment_date)
        except ValueError as exc:
            raise ValueError("CONSERVATION_ASSESSMENT_DATE_INVALID") from exc
        if assessed > self.as_of:
            raise ValueError("CONSERVATION_ASSESSMENT_DATE_FUTURE")
        years = (self.as_of - assessed).days / 365.2425
        return {
            "as_of": self.as_of.isoformat(),
            "age_years": round(years, 3),
            "stale_after_years": self.stale_after_years,
            "state": "stale" if years > self.stale_after_years else "current",
        }

    def record(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        assessment_id = _text(payload.get("assessment_id"))
        if not assessment_id:
            raise ValueError("CONSERVATION_ASSESSMENT_ID_REQUIRED")
        taxon = payload.get("taxon")
        if not isinstance(taxon, dict):
            raise TypeError("CONSERVATION_TAXON_REQUIRED")
        taxon_key_value, taxon_name = self._taxon_identity(taxon)

        authority = _text(payload.get("source_authority"))
        version = _text(payload.get("assessment_version"))
        assessment_date = _text(payload.get("assessment_date"))
        category_system = _text(payload.get("category_system"))
        category = _text(payload.get("category"))
        if not all((authority, version, assessment_date, category_system, category)):
            raise ValueError("CONSERVATION_ASSESSMENT_FIELDS_REQUIRED")
        if "iucn" in category_system.casefold() and authority.casefold() not in {"iucn", "international union for conservation of nature"}:
            raise ValueError("CONSERVATION_IUCN_AUTHORITY_REQUIRED")

        evidence_ref = payload.get("evidence")
        if not isinstance(evidence_ref, dict):
            raise TypeError("CONSERVATION_EVIDENCE_REQUIRED")
        run_id = _text(evidence_ref.get("literature_run_id"))
        span_id = int(evidence_ref.get("span_id", 0))
        if not run_id or span_id < 1:
            raise ValueError("CONSERVATION_EVIDENCE_REFERENCE_INVALID")
        evidence = self._bind_evidence(run_id, span_id)

        confidence = float(payload.get("confidence", -1))
        if not 0 <= confidence <= 1:
            raise ValueError("CONSERVATION_CONFIDENCE_INVALID")
        conflicts = list(payload.get("conflicts") or [])
        threats = list(payload.get("threats") or [])
        protected_areas = list(payload.get("protected_areas") or [])
        actions = list(payload.get("actions") or [])
        population = payload.get("population") or {}
        if not isinstance(population, dict):
            raise TypeError("CONSERVATION_POPULATION_INVALID")
        occurrence_evidence_ids = sorted({_text(item) for item in payload.get("occurrence_evidence_ids", []) if _text(item)})
        atlas_feature_ids = sorted({_text(item) for item in payload.get("atlas_feature_ids", []) if _text(item)})
        freshness = self._freshness(assessment_date)

        review_reasons: list[str] = []
        if freshness["state"] == "stale":
            review_reasons.append("stale_assessment")
        if conflicts:
            review_reasons.append("conflicting_assessments_or_evidence")
        if confidence < 0.7:
            review_reasons.append("low_confidence")
        if not threats:
            review_reasons.append("threats_not_supplied")

        record = {
            "schema_version": SCHEMA_VERSION,
            "assessment_id": assessment_id,
            "taxon_key": taxon_key_value,
            "scientific_name": taxon_name,
            "source_authority": authority,
            "assessment_version": version,
            "assessment_date": assessment_date,
            "category_system": category_system,
            "category": category,
            "population": population,
            "trend": _text(payload.get("trend")) or None,
            "threats": threats,
            "protected_areas": protected_areas,
            "actions": actions,
            "evidence": evidence,
            "confidence": confidence,
            "conflicts": conflicts,
            "freshness": freshness,
            "occurrence_evidence_ids": occurrence_evidence_ids,
            "atlas_feature_ids": atlas_feature_ids,
            "review_status": "review_required" if review_reasons else "candidate_ready",
            "review_reasons": sorted(set(review_reasons)),
            "provenance": {
                "source_authority": authority,
                "assessment_version": version,
                "assessment_date": assessment_date,
                "literature_run_id": run_id,
                "evidence_span_id": span_id,
                "evidence_sha256": evidence["sha256"],
                "occurrence_evidence_ids": occurrence_evidence_ids,
                "atlas_feature_ids": atlas_feature_ids,
                "fabricated_iucn_status_authorized": False,
                "scientific_publication_authorized": False,
                "production_graph_mutation_authorized": False,
            },
        }
        record["record_digest"] = _digest(record)
        return self._write(self._root(owner_id) / "records" / f"{assessment_id}.json", record)

    def get(self, owner_id: str, assessment_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "records" / f"{assessment_id}.json")

    def review_queue(self, owner_id: str) -> dict[str, Any]:
        directory = self._root(owner_id) / "records"
        records = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                record = self._read(path)
                if record["review_status"] == "review_required":
                    records.append(record)
        return {"schema_version": SCHEMA_VERSION, "count": len(records), "records": records}

    def stage(self, owner_id: str, *, limit: int = 100) -> dict[str, Any]:
        if limit < 1 or limit > 5000:
            raise ValueError("CONSERVATION_STAGE_LIMIT_INVALID")
        directory = self._root(owner_id) / "records"
        candidates = []
        if directory.exists():
            candidates = [self._read(path) for path in sorted(directory.glob("*.json"))]
            candidates = [item for item in candidates if item["review_status"] == "candidate_ready"]
        selected = candidates[:limit]
        path = self._root(owner_id) / "staging" / "assessments.json"
        current = self._read(path) if path.exists() else {"assessments": []}
        existing = {item["record_digest"] for item in current["assessments"]}
        additions = [item for item in selected if item["record_digest"] not in existing]
        merged = current["assessments"] + additions
        self._write(path, {"schema_version": SCHEMA_VERSION, "assessments": merged})
        return {
            "schema_version": SCHEMA_VERSION,
            "examined": len(selected),
            "added": len(additions),
            "already_staged": len(selected) - len(additions),
            "total_staged": len(merged),
            "bounded": True,
            "production_graph_mutation_performed": False,
            "scientific_publication_performed": False,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        directory = self._root(owner_id) / "records"
        records = [self._read(path) for path in sorted(directory.glob("*.json"))] if directory.exists() else []
        ready = [item for item in records if item["review_status"] == "candidate_ready"]
        stale = [item for item in records if item["freshness"]["state"] == "stale"]
        review = [item for item in records if item["review_status"] == "review_required"]
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": "REVIEW_READY" if ready else "NO_CURRENT_CANDIDATE_ASSESSMENTS",
            "record_count": len(records),
            "candidate_ready_count": len(ready),
            "review_required_count": len(review),
            "stale_assessment_count": len(stale),
            "fabricated_iucn_status_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "production_deployment_authorized": False,
        }
