"""Durable, review-only occurrence persistence for CALYX issue #462.

This module ingests bounded GBIF/iNaturalist occurrence records, preserves immutable
raw source evidence, normalizes records deterministically, reconciles exact taxon
identities against a reviewed taxonomy staging artifact, and projects normalized
records into a resumable local staging artifact. It deliberately has no production
Knowledge Graph mutation, taxonomy activation, or unbounded harvesting capability.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from runtime.taxonomy_preflight import normalize

OCCURRENCE_SCHEMA_VERSION = "1.0.0"
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
SUPPORTED_SOURCES = {"gbif", "inaturalist"}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _json(path: Path, payload: Any) -> None:
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _row_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _first(record: dict[str, Any], *names: str) -> Any:
    folded = {str(key).casefold(): value for key, value in record.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value is not None and str(value).strip() != "":
            return value
    return None


def _text(record: dict[str, Any], *names: str) -> str:
    value = _first(record, *names)
    return normalize(value) if value is not None else ""


def _float(record: dict[str, Any], *names: str) -> float | None:
    value = _first(record, *names)
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalized_name(name: str) -> str:
    return " ".join(normalize(name).casefold().split())


def _source_record_id(source: str, record: dict[str, Any]) -> str:
    if source == "gbif":
        value = _text(record, "key", "gbifID", "occurrenceID")
    else:
        value = _text(record, "id", "uuid", "uri", "occurrenceID")
    if not value:
        raise ValueError(f"{source} occurrence record lacks a stable source identifier")
    return value


def _coordinate_state(latitude: float | None, longitude: float | None) -> str:
    if latitude is None and longitude is None:
        return "missing"
    if latitude is None or longitude is None:
        return "invalid"
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return "invalid"
    return "valid"


@dataclass(frozen=True)
class OccurrenceBatchIdentity:
    batch_id: str
    source: str
    sha256: str
    record_count: int


class CanonicalTaxonIndex:
    """Exact reviewed taxonomy lookup built from a local JSONL staging artifact."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self.by_name: dict[str, list[dict[str, str]]] = {}
        self.by_key: dict[str, dict[str, str]] = {}
        for row in rows:
            taxon_key = normalize(row.get("taxon_key"))
            name = normalize(row.get("scientific_name"))
            if not taxon_key or not name:
                continue
            candidate = {
                "canonical_taxon_id": taxon_key,
                "taxon_key": taxon_key,
                "scientific_name": name,
            }
            self.by_key[taxon_key] = candidate
            self.by_name.setdefault(_normalized_name(name), []).append(candidate)

    @classmethod
    def from_path(cls, path: Path | None) -> "CanonicalTaxonIndex":
        if path is None:
            return cls([])
        if not path.is_file():
            raise ValueError("configured taxonomy staging artifact is not a regular file")
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(rows)

    def resolve(self, scientific_name: str, supplied_taxon_key: str = "") -> dict[str, Any]:
        if supplied_taxon_key and supplied_taxon_key in self.by_key:
            return {"state": "matched", **self.by_key[supplied_taxon_key], "method": "taxon_key"}
        matches = self.by_name.get(_normalized_name(scientific_name), []) if scientific_name else []
        unique = {item["canonical_taxon_id"]: item for item in matches}
        if len(unique) == 1:
            item = next(iter(unique.values()))
            return {"state": "matched", **item, "method": "scientific_name_exact"}
        if len(unique) > 1:
            return {
                "state": "ambiguous",
                "canonical_taxon_id": None,
                "method": "scientific_name_exact",
                "candidate_ids": sorted(unique),
            }
        return {"state": "unmatched", "canonical_taxon_id": None, "method": "none"}


class OccurrencePersistenceService:
    def __init__(
        self,
        workspace: Path,
        *,
        maximum_records: int = 5000,
        maximum_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self.workspace = workspace
        self.maximum_records = maximum_records
        self.maximum_bytes = maximum_bytes

    def _batch_dir(self, batch_id: str) -> Path:
        safe = SAFE_ID_RE.sub("_", batch_id)
        if safe != batch_id or not batch_id:
            raise ValueError("invalid batch_id")
        return self.workspace / "batches" / batch_id

    def intake_records(
        self,
        source: str,
        records: list[dict[str, Any]],
        *,
        taxonomy_staging_path: Path | None = None,
    ) -> dict[str, Any]:
        source_name = source.strip().casefold()
        if source_name not in SUPPORTED_SOURCES:
            raise ValueError("source must be gbif or inaturalist")
        if not records:
            raise ValueError("occurrence batch is empty")
        if len(records) > self.maximum_records:
            raise ValueError(f"occurrence batch exceeds maximum_records={self.maximum_records}")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("all occurrence records must be JSON objects")

        raw_text = "".join(_stable_json(record) + "\n" for record in records)
        raw_bytes = raw_text.encode("utf-8")
        if len(raw_bytes) > self.maximum_bytes:
            raise ValueError(f"occurrence batch exceeds maximum_bytes={self.maximum_bytes}")
        digest = _sha256_bytes(raw_bytes)
        batch_id = f"occ-{source_name}-{digest[:20]}"
        root = self._batch_dir(batch_id)
        raw_path = root / "raw.jsonl"
        if raw_path.exists():
            if raw_path.read_bytes() != raw_bytes:
                raise RuntimeError("immutable occurrence batch digest collision")
        else:
            _atomic_write(raw_path, raw_text)

        index = CanonicalTaxonIndex.from_path(taxonomy_staging_path)
        normalized_rows: list[dict[str, Any]] = []
        review_queue: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for row_number, record in enumerate(records, start=1):
            source_id = _source_record_id(source_name, record)
            if source_id in seen_source_ids:
                raise ValueError(f"duplicate source record identifier in batch: {source_id}")
            seen_source_ids.add(source_id)
            scientific_name = _text(record, "scientificName", "taxon.name", "species_guess", "name")
            supplied_taxon_key = _text(record, "taxon_key", "taxonKey", "acceptedTaxonKey")
            latitude = _float(record, "decimalLatitude", "latitude", "geojson.coordinates.1")
            longitude = _float(record, "decimalLongitude", "longitude", "geojson.coordinates.0")
            uncertainty = _float(record, "coordinateUncertaintyInMeters", "positional_accuracy")
            if uncertainty is not None and uncertainty < 0:
                uncertainty = None
            coordinate_state = _coordinate_state(latitude, longitude)
            reconciliation = index.resolve(scientific_name, supplied_taxon_key)
            normalized_row: dict[str, Any] = {
                "schema_version": OCCURRENCE_SCHEMA_VERSION,
                "source": source_name,
                "source_record_id": source_id,
                "row_number": row_number,
                "scientific_name": scientific_name,
                "supplied_taxon_key": supplied_taxon_key or None,
                "canonical_taxon_id": reconciliation.get("canonical_taxon_id"),
                "reconciliation_state": reconciliation["state"],
                "reconciliation_method": reconciliation["method"],
                "decimal_latitude": latitude,
                "decimal_longitude": longitude,
                "coordinate_uncertainty_m": uncertainty,
                "coordinate_state": coordinate_state,
                "event_date": _text(record, "eventDate", "observed_on", "time_observed_at") or None,
                "country_code": _text(record, "countryCode", "place_country_code") or None,
                "basis_of_record": _text(record, "basisOfRecord", "quality_grade") or None,
                "source_record": record,
            }
            normalized_row["row_sha256"] = _row_sha(normalized_row)
            normalized_rows.append(normalized_row)
            reasons: list[str] = []
            if reconciliation["state"] != "matched":
                reasons.append(f"taxon_{reconciliation['state']}")
            if coordinate_state == "invalid":
                reasons.append("invalid_coordinates")
            if reasons:
                review_queue.append(
                    {
                        "source": source_name,
                        "source_record_id": source_id,
                        "scientific_name": scientific_name,
                        "row_sha256": normalized_row["row_sha256"],
                        "reasons": reasons,
                        "candidate_taxon_ids": reconciliation.get("candidate_ids", []),
                        "review_state": "pending",
                    }
                )

        normalized_text = "".join(_stable_json(row) + "\n" for row in normalized_rows)
        normalized_sha = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        identity = OccurrenceBatchIdentity(batch_id, source_name, digest, len(records))
        _atomic_write(root / "normalized.jsonl", normalized_text)
        _json(root / "review_queue.json", review_queue)
        _json(
            root / "manifest.json",
            {
                "schema_version": OCCURRENCE_SCHEMA_VERSION,
                "identity": asdict(identity),
                "normalized_sha256": normalized_sha,
                "matched_taxa": sum(1 for row in normalized_rows if row["reconciliation_state"] == "matched"),
                "unmatched_taxa": sum(1 for row in normalized_rows if row["reconciliation_state"] == "unmatched"),
                "ambiguous_taxa": sum(1 for row in normalized_rows if row["reconciliation_state"] == "ambiguous"),
                "invalid_coordinate_records": sum(1 for row in normalized_rows if row["coordinate_state"] == "invalid"),
                "review_queue_count": len(review_queue),
                "taxonomy_staging_configured": taxonomy_staging_path is not None,
                "knowledge_graph_mutation_authorized": False,
                "taxonomy_activation_authorized": False,
                "unbounded_harvest_authorized": False,
            },
        )
        if not (root / "checkpoint.json").exists():
            _json(root / "checkpoint.json", {"next_offset": 0, "complete": False, "projected_unique_rows": 0})
        return self.readiness(batch_id)

    def project_staging(self, batch_id: str, *, batch_size: int = 500) -> dict[str, Any]:
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        root = self._batch_dir(batch_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown occurrence batch: {batch_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (root / "normalized.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        checkpoint_path = root / "checkpoint.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("complete"):
            return self.readiness(batch_id)
        offset = int(checkpoint.get("next_offset", 0))
        end = min(offset + batch_size, len(rows))
        staging_path = root / "staging.jsonl"
        existing: dict[str, dict[str, Any]] = {}
        if staging_path.exists():
            for line in staging_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    existing[row["row_sha256"]] = row
        for row in rows[offset:end]:
            existing.setdefault(row["row_sha256"], row)
        ordered = sorted(existing.values(), key=lambda item: (item["source"], item["source_record_id"], item["row_sha256"]))
        _atomic_write(staging_path, "".join(_stable_json(row) + "\n" for row in ordered))
        _json(
            checkpoint_path,
            {
                "next_offset": end,
                "complete": end >= len(rows),
                "projected_unique_rows": len(ordered),
                "normalized_sha256": manifest["normalized_sha256"],
            },
        )
        return self.readiness(batch_id)

    def review_queue(self, batch_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        root = self._batch_dir(batch_id)
        path = root / "review_queue.json"
        if not path.exists():
            raise FileNotFoundError(f"unknown occurrence batch: {batch_id}")
        queue = json.loads(path.read_text(encoding="utf-8"))
        return {
            "batch_id": batch_id,
            "total": len(queue),
            "offset": offset,
            "limit": limit,
            "items": queue[offset : offset + limit],
            "review_write_authorized": False,
        }

    def readiness(self, batch_id: str) -> dict[str, Any]:
        root = self._batch_dir(batch_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown occurrence batch: {batch_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
        ready_for_review = bool(checkpoint.get("complete"))
        return {
            "schema_version": OCCURRENCE_SCHEMA_VERSION,
            "batch_id": batch_id,
            "identity": manifest["identity"],
            "normalized_sha256": manifest["normalized_sha256"],
            "matched_taxa": manifest["matched_taxa"],
            "unmatched_taxa": manifest["unmatched_taxa"],
            "ambiguous_taxa": manifest["ambiguous_taxa"],
            "invalid_coordinate_records": manifest["invalid_coordinate_records"],
            "review_queue_count": manifest["review_queue_count"],
            "taxonomy_staging_configured": manifest["taxonomy_staging_configured"],
            "staging_next_offset": int(checkpoint.get("next_offset", 0)),
            "staging_complete": bool(checkpoint.get("complete")),
            "projected_unique_rows": int(checkpoint.get("projected_unique_rows", 0)),
            "decision": "REVIEW_ONLY" if ready_for_review else "HOLD",
            "ready_for_review": ready_for_review,
            "ready_for_publication": False,
            "knowledge_graph_mutation_authorized": False,
            "taxonomy_activation_authorized": False,
            "unbounded_harvest_authorized": False,
        }
