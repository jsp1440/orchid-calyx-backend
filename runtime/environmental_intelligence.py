"""Governed climate, habitat, elevation, and environmental-envelope intelligence."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import ArtifactRegistration, ImmutableArtifactRegistry

SCHEMA_VERSION = "calyx-environmental-intelligence/v1"
OBSERVATION_STATES = {"observed", "modeled"}
REVIEW_STATES = {"candidate", "needs_review", "accepted_as_evidence", "rejected"}


def environmental_root() -> Path:
    return Path(os.environ.get("CALYX_ENVIRONMENT_WORKSPACE", "/tmp/calyx/environmental-intelligence"))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_id(value: object, code: str) -> str:
    text = _text(value)
    if not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        raise ValueError(code)
    return text


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("ENV_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode("utf-8")).hexdigest()[:20]


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


class EnvironmentalIntelligenceService:
    def __init__(self, workspace: Path | None = None, *, artifacts: ImmutableArtifactRegistry | None = None) -> None:
        self.workspace = workspace or environmental_root()
        self.artifacts = artifacts or ImmutableArtifactRegistry()

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

    def register_record(self, owner_id: str, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        record_id = _safe_id(payload.get("record_id"), "ENV_RECORD_ID_INVALID")
        canonical_taxon_id = _text(payload.get("canonical_taxon_id"))
        accepted_name = _text(payload.get("accepted_name"))
        state = _text(payload.get("observation_state"))
        if not canonical_taxon_id or not accepted_name:
            raise ValueError("ENV_TAXON_LINKAGE_REQUIRED")
        if state not in OBSERVATION_STATES:
            raise ValueError("ENV_OBSERVATION_STATE_INVALID")
        source = dict(payload.get("source") or {})
        if not _text(source.get("uri")) or not _text(source.get("license")):
            raise ValueError("ENV_SOURCE_LICENSE_REQUIRED")
        temporal = dict(payload.get("temporal_coverage") or {})
        spatial = dict(payload.get("spatial_resolution") or {})
        if not spatial:
            raise ValueError("ENV_SPATIAL_RESOLUTION_REQUIRED")
        variables = dict(payload.get("climate_variables") or {})
        elevation = dict(payload.get("elevation") or {})
        substrate = list(payload.get("substrate") or [])
        habitat = list(payload.get("habitat") or [])
        uncertainty = dict(payload.get("uncertainty") or {})
        provenance = dict(payload.get("provenance") or {})
        if not provenance:
            raise ValueError("ENV_PROVENANCE_REQUIRED")
        if not any((variables, elevation, substrate, habitat)):
            raise ValueError("ENV_MEASUREMENT_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_id": record_id,
            "canonical_taxon_id": canonical_taxon_id,
            "accepted_name": accepted_name,
            "occurrence_id": _text(payload.get("occurrence_id")) or None,
            "climate_variables": variables,
            "elevation": elevation,
            "substrate": substrate,
            "habitat": habitat,
            "temporal_coverage": temporal,
            "spatial_resolution": spatial,
            "source": source,
            "observation_state": state,
            "uncertainty": uncertainty,
            "provenance": provenance,
            "review_state": _text(payload.get("review_state")) or "candidate",
            "unsupported_causal_claims_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "created_by": _text(actor),
            "created_at": _now(),
        }
        if record["review_state"] not in REVIEW_STATES:
            raise ValueError("ENV_REVIEW_STATE_INVALID")
        record["record_digest"] = _digest(record)
        return self._write(self._root(owner_id) / "records" / f"{record_id}.json", record)

    def review_record(self, owner_id: str, record_id: str, *, state: str, reviewer: str, rationale: str) -> dict[str, Any]:
        if state not in REVIEW_STATES:
            raise ValueError("ENV_REVIEW_STATE_INVALID")
        if not _text(reviewer) or not _text(rationale):
            raise ValueError("ENV_REVIEW_FIELDS_REQUIRED")
        safe_id = _safe_id(record_id, "ENV_RECORD_ID_INVALID")
        path = self._root(owner_id) / "records" / f"{safe_id}.json"
        record = self._read(path)
        history = list(record.get("review_history") or [])
        history.append({"from": record["review_state"], "to": state, "reviewer": reviewer, "rationale": rationale, "at": _now()})
        record["review_state"] = state
        record["review_history"] = history
        record["updated_at"] = _now()
        return self._write(path, record)

    def _taxon_records(self, owner_id: str, canonical_taxon_id: str) -> list[dict[str, Any]]:
        records_dir = self._root(owner_id) / "records"
        records = []
        if records_dir.exists():
            for path in sorted(records_dir.glob("*.json")):
                item = self._read(path)
                if item["canonical_taxon_id"] == canonical_taxon_id:
                    records.append(item)
        return records

    def assemble_envelope(self, owner_id: str, canonical_taxon_id: str) -> dict[str, Any]:
        taxon_id = _text(canonical_taxon_id)
        if not taxon_id:
            raise ValueError("ENV_TAXON_LINKAGE_REQUIRED")
        records = self._taxon_records(owner_id, taxon_id)
        if not records:
            raise LookupError("ENV_TAXON_RECORDS_NOT_FOUND")
        accepted = [item for item in records if item["review_state"] == "accepted_as_evidence"]
        working = accepted or records
        variables: dict[str, list[float]] = defaultdict(list)
        observed_count = 0
        modeled_count = 0
        elevation_values: list[float] = []
        source_uris: set[str] = set()
        spatial_cells: set[str] = set()
        habitats: set[str] = set()
        substrates: set[str] = set()
        for item in working:
            if item["observation_state"] == "observed":
                observed_count += 1
            else:
                modeled_count += 1
            source_uris.add(str(item["source"]["uri"]))
            cell = _text(item["spatial_resolution"].get("cell_id") or item["spatial_resolution"].get("description"))
            if cell:
                spatial_cells.add(cell)
            for name, value in item["climate_variables"].items():
                try:
                    variables[name].append(float(value))
                except (TypeError, ValueError):
                    continue
            for key in ("meters", "value_m"):
                if key in item["elevation"]:
                    try:
                        elevation_values.append(float(item["elevation"][key]))
                    except (TypeError, ValueError):
                        pass
            habitats.update(_text(value) for value in item["habitat"] if _text(value))
            substrates.update(_text(value) for value in item["substrate"] if _text(value))
        variable_envelopes = {
            name: {"min": min(values), "max": max(values), "n": len(values)}
            for name, values in sorted(variables.items())
            if values
        }
        warnings: list[str] = []
        if len(working) < 5:
            warnings.append("LOW_SAMPLE_COUNT")
        if len(spatial_cells) <= 1 and len(working) > 1:
            warnings.append("SPATIAL_CLUSTERING_RISK")
        if modeled_count and observed_count == 0:
            warnings.append("MODELED_ONLY_ENVELOPE")
        if accepted == []:
            warnings.append("UNREVIEWED_RECORDS_USED")
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "canonical_taxon_id": taxon_id,
            "accepted_name": working[0]["accepted_name"],
            "record_count": len(working),
            "observed_record_count": observed_count,
            "modeled_record_count": modeled_count,
            "climate_envelope": variable_envelopes,
            "elevation_envelope_m": ({"min": min(elevation_values), "max": max(elevation_values), "n": len(elevation_values)} if elevation_values else None),
            "habitat_terms": sorted(habitats),
            "substrate_terms": sorted(substrates),
            "source_uris": sorted(source_uris),
            "sampling_bias_warnings": warnings,
            "causal_interpretation": "not_authorized",
            "review_basis": "accepted_as_evidence" if accepted else "candidate_records",
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
        }
        envelope["envelope_digest"] = _digest(envelope)
        return envelope

    def atlas_handoff(self, owner_id: str, canonical_taxon_id: str) -> dict[str, Any]:
        envelope = self.assemble_envelope(owner_id, canonical_taxon_id)
        content = _stable(envelope).encode("utf-8")
        result = self.artifacts.register(
            ArtifactRegistration(
                artifact_id=f"atlas-environment:{envelope['canonical_taxon_id']}:{envelope['envelope_digest']}",
                content=content,
                media_type="application/json",
                source_uri=f"calyx://environment/envelopes/{envelope['canonical_taxon_id']}/{envelope['envelope_digest']}",
                producer_assignment_id="CALYX-478-environmental-intelligence",
                evidence_uris=tuple(envelope["source_uris"]),
                metadata={
                    "atlas_layer_family": "earth_systems.environmental_envelope",
                    "canonical_taxon_id": envelope["canonical_taxon_id"],
                    "causal_interpretation": "not_authorized",
                    "publication_authorized": False,
                },
            )
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "atlas_layer_family": "earth_systems.environmental_envelope",
            "canonical_taxon_id": envelope["canonical_taxon_id"],
            "artifact_id": result.record.artifact_id,
            "artifact_checksum": result.record.checksum,
            "envelope": envelope,
            "provenance_required": True,
            "uncertainty_preserved": True,
            "sampling_bias_warnings": envelope["sampling_bias_warnings"],
            "publication_status": "candidate",
            "scientific_publication_authorized": False,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        records_dir = self._root(owner_id) / "records"
        records = [self._read(path) for path in sorted(records_dir.glob("*.json"))] if records_dir.exists() else []
        pending = [item["record_id"] for item in records if item["review_state"] in {"candidate", "needs_review"}]
        modeled = [item["record_id"] for item in records if item["observation_state"] == "modeled"]
        return {
            "schema_version": SCHEMA_VERSION,
            "record_count": len(records),
            "pending_review_ids": pending,
            "modeled_record_ids": modeled,
            "atlas_handoff_available": bool(records),
            "unsupported_causal_claims_authorized": False,
            "live_production_import_authorized": False,
            "scientific_publication_authorized": False,
            "production_graph_mutation_authorized": False,
            "deployment_authorized": False,
        }
