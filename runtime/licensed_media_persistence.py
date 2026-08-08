"""Bounded, review-only licensed-media persistence for CALYX issue #463.

The service validates explicit media metadata, enforces an allowlist of redistributable
licenses, preserves immutable normalized records, reconciles taxa against reviewed
#461 staging, records duplicate/ambiguity review items, and projects records into a
resumable local staging artifact. It has no publication or production graph writer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.calyx_orchestrator.artifact_registry import ArtifactRegistration, ImmutableArtifactRegistry
from runtime.taxonomy_preflight import normalize

MEDIA_SCHEMA_VERSION = "1.0.0"
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


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _row_digest(payload: dict[str, Any]) -> str:
    return _digest(_stable_json(payload).encode("utf-8"))


def _text(record: dict[str, Any], *names: str) -> str:
    folded = {str(key).casefold(): value for key, value in record.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value is not None and str(value).strip():
            return normalize(str(value))
    return ""


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _license(value: str) -> str:
    normalized = normalize(value).casefold()
    normalized = LICENSE_ALIASES.get(normalized, normalized.replace("_", "-"))
    if normalized not in ALLOWED_LICENSES:
        raise ValueError(f"MEDIA_LICENSE_NOT_ALLOWED:{value}")
    return normalized


def _norm_name(value: str) -> str:
    return " ".join(normalize(value).casefold().split())


@dataclass(frozen=True)
class MediaBatchIdentity:
    batch_id: str
    sha256: str
    record_count: int


class ReviewedTaxonIndex:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.by_key: dict[str, dict[str, str]] = {}
        self.by_name: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            key = normalize(str(row.get("taxon_key") or ""))
            name = normalize(str(row.get("scientific_name") or ""))
            if not key or not name:
                continue
            item = {"canonical_taxon_id": key, "taxon_key": key, "scientific_name": name}
            self.by_key[key] = item
            self.by_name.setdefault(_norm_name(name), []).append(item)

    @classmethod
    def from_path(cls, path: Path | None) -> ReviewedTaxonIndex:
        if path is None:
            return cls([])
        if not path.is_file():
            raise ValueError("configured taxonomy staging artifact is not a regular file")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return cls(rows)

    def resolve(self, scientific_name: str, supplied_key: str) -> dict[str, Any]:
        if supplied_key and supplied_key in self.by_key:
            return {"state": "matched", **self.by_key[supplied_key], "method": "taxon_key"}
        matches = self.by_name.get(_norm_name(scientific_name), []) if scientific_name else []
        unique = {item["canonical_taxon_id"]: item for item in matches}
        if len(unique) == 1:
            item = next(iter(unique.values()))
            return {"state": "matched", **item, "method": "scientific_name_exact"}
        if len(unique) > 1:
            return {"state": "ambiguous", "canonical_taxon_id": None, "candidate_ids": sorted(unique), "method": "scientific_name_exact"}
        return {"state": "unmatched", "canonical_taxon_id": None, "candidate_ids": [], "method": "none"}


class LicensedMediaPersistenceService:
    def __init__(
        self,
        workspace: Path,
        *,
        maximum_records: int = 2000,
        registry: ImmutableArtifactRegistry | None = None,
    ) -> None:
        self.workspace = workspace
        self.maximum_records = maximum_records
        self.registry = registry or ImmutableArtifactRegistry()

    def _batch_dir(self, batch_id: str) -> Path:
        if not batch_id or SAFE_ID_RE.sub("_", batch_id) != batch_id:
            raise ValueError("invalid batch_id")
        return self.workspace / "batches" / batch_id

    def intake_records(
        self,
        records: list[dict[str, Any]],
        *,
        taxonomy_staging_path: Path | None = None,
    ) -> dict[str, Any]:
        if not records:
            raise ValueError("media batch is empty")
        if len(records) > self.maximum_records:
            raise ValueError(f"media batch exceeds maximum_records={self.maximum_records}")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("all media records must be JSON objects")

        raw_text = "".join(_stable_json(record) + "\n" for record in records)
        identity_digest = _digest(raw_text.encode("utf-8"))
        batch_id = f"media-{identity_digest[:20]}"
        root = self._batch_dir(batch_id)
        raw_path = root / "raw.jsonl"
        if raw_path.exists() and raw_path.read_text(encoding="utf-8") != raw_text:
            raise RuntimeError("immutable media batch digest collision")
        if not raw_path.exists():
            _atomic_write(raw_path, raw_text)

        taxa = ReviewedTaxonIndex.from_path(taxonomy_staging_path)
        normalized_rows: list[dict[str, Any]] = []
        review_queue: list[dict[str, Any]] = []
        seen_urls: dict[str, str] = {}
        seen_hashes: dict[str, str] = {}

        for row_number, record in enumerate(records, start=1):
            provider = _text(record, "provider", "source_provider")
            source_url = _text(record, "source_url", "url", "source")
            creator = _text(record, "creator", "photographer", "author")
            attribution = _text(record, "attribution", "credit")
            license_name = _license(_text(record, "license", "license_code"))
            checksum = _text(record, "checksum", "sha256").casefold()
            media_type = _text(record, "media_type", "mime_type") or "image/jpeg"
            scientific_name = _text(record, "scientific_name", "scientificName")
            supplied_key = _text(record, "taxon_key", "canonical_taxon_id")
            acquired_at = _text(record, "acquired_at", "acquisition_time")

            if not provider:
                raise ValueError("MEDIA_PROVIDER_REQUIRED")
            if not _valid_http_url(source_url):
                raise ValueError("MEDIA_SOURCE_URL_INVALID")
            if not creator or not attribution:
                raise ValueError("MEDIA_ATTRIBUTION_REQUIRED")
            if not SHA256_RE.fullmatch(checksum):
                raise ValueError("MEDIA_SHA256_INVALID")
            if "/" not in media_type:
                raise ValueError("MEDIA_TYPE_INVALID")
            if not acquired_at:
                raise ValueError("MEDIA_ACQUISITION_TIME_REQUIRED")

            reconciliation = taxa.resolve(scientific_name, supplied_key)
            normalized: dict[str, Any] = {
                "schema_version": MEDIA_SCHEMA_VERSION,
                "row_number": row_number,
                "provider": provider,
                "source_url": source_url,
                "creator": creator,
                "attribution": attribution,
                "license": license_name,
                "sha256": checksum,
                "media_type": media_type,
                "acquired_at": acquired_at,
                "scientific_name": scientific_name,
                "supplied_taxon_key": supplied_key or None,
                "canonical_taxon_id": reconciliation.get("canonical_taxon_id"),
                "taxon_resolution_state": reconciliation["state"],
                "taxon_resolution_method": reconciliation["method"],
                "source_record": record,
            }
            normalized["row_sha256"] = _row_digest(normalized)

            reasons: list[str] = []
            prior_url_hash = seen_urls.get(source_url)
            if prior_url_hash is not None:
                reasons.append("duplicate_url" if prior_url_hash == checksum else "conflicting_url_checksum")
            prior_hash_url = seen_hashes.get(checksum)
            if prior_hash_url is not None and prior_hash_url != source_url:
                reasons.append("duplicate_content_different_url")
            if reconciliation["state"] != "matched":
                reasons.append(f"taxon_{reconciliation['state']}")

            seen_urls.setdefault(source_url, checksum)
            seen_hashes.setdefault(checksum, source_url)
            normalized_rows.append(normalized)

            artifact_content = _stable_json({key: normalized[key] for key in (
                "provider", "source_url", "creator", "attribution", "license", "sha256",
                "media_type", "canonical_taxon_id", "scientific_name", "acquired_at"
            )}).encode("utf-8")
            artifact_id = f"media-metadata:{normalized['row_sha256']}"
            self.registry.register(ArtifactRegistration(
                artifact_id=artifact_id,
                content=artifact_content,
                media_type="application/json",
                source_uri=source_url,
                producer_assignment_id=f"calyx-463:{batch_id}",
                license=license_name,
                evidence_uris=(source_url,),
                metadata={"media_sha256": checksum, "provider": provider},
            ))
            self.registry.require_evidence(artifact_id)

            if reasons:
                review_queue.append({
                    "row_number": row_number,
                    "source_url": source_url,
                    "sha256": checksum,
                    "scientific_name": scientific_name,
                    "reasons": reasons,
                    "candidate_taxon_ids": reconciliation.get("candidate_ids", []),
                    "review_state": "pending",
                })

        normalized_text = "".join(_stable_json(row) + "\n" for row in normalized_rows)
        normalized_sha = _digest(normalized_text.encode("utf-8"))
        identity = MediaBatchIdentity(batch_id, identity_digest, len(records))
        _atomic_write(root / "normalized.jsonl", normalized_text)
        _json(root / "review_queue.json", review_queue)
        _json(root / "artifact_registry_snapshot.json", self.registry.snapshot())
        _json(root / "manifest.json", {
            "schema_version": MEDIA_SCHEMA_VERSION,
            "identity": asdict(identity),
            "normalized_sha256": normalized_sha,
            "matched_taxa": sum(row["taxon_resolution_state"] == "matched" for row in normalized_rows),
            "unmatched_taxa": sum(row["taxon_resolution_state"] == "unmatched" for row in normalized_rows),
            "ambiguous_taxa": sum(row["taxon_resolution_state"] == "ambiguous" for row in normalized_rows),
            "review_queue_count": len(review_queue),
            "duplicate_url_count": sum("duplicate_url" in item["reasons"] for item in review_queue),
            "conflicting_url_checksum_count": sum("conflicting_url_checksum" in item["reasons"] for item in review_queue),
            "duplicate_content_count": sum("duplicate_content_different_url" in item["reasons"] for item in review_queue),
            "taxonomy_staging_configured": taxonomy_staging_path is not None,
            "license_allowlist": sorted(ALLOWED_LICENSES),
            "artifact_registry_artifact_count": self.registry.snapshot()["artifact_count"],
            "publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        })
        if not (root / "checkpoint.json").exists():
            _json(root / "checkpoint.json", {"next_offset": 0, "complete": False, "projected_unique_rows": 0})
        return self.readiness(batch_id)

    def project_staging(self, batch_id: str, *, batch_size: int = 500) -> dict[str, Any]:
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        root = self._batch_dir(batch_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown media batch: {batch_id}")
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
        ordered = sorted(existing.values(), key=lambda item: (item["source_url"], item["row_sha256"]))
        _atomic_write(staging_path, "".join(_stable_json(row) + "\n" for row in ordered))
        _json(checkpoint_path, {
            "next_offset": end,
            "complete": end >= len(rows),
            "projected_unique_rows": len(ordered),
            "normalized_sha256": manifest["normalized_sha256"],
        })
        return self.readiness(batch_id)

    def review_queue(self, batch_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        path = self._batch_dir(batch_id) / "review_queue.json"
        if not path.exists():
            raise FileNotFoundError(f"unknown media batch: {batch_id}")
        queue = json.loads(path.read_text(encoding="utf-8"))
        return {"batch_id": batch_id, "total": len(queue), "offset": offset, "limit": limit, "items": queue[offset:offset + limit], "review_write_authorized": False}

    def readiness(self, batch_id: str) -> dict[str, Any]:
        root = self._batch_dir(batch_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown media batch: {batch_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
        ready_for_review = bool(checkpoint.get("complete"))
        return {
            "schema_version": MEDIA_SCHEMA_VERSION,
            "batch_id": batch_id,
            "identity": manifest["identity"],
            "normalized_sha256": manifest["normalized_sha256"],
            "matched_taxa": manifest["matched_taxa"],
            "unmatched_taxa": manifest["unmatched_taxa"],
            "ambiguous_taxa": manifest["ambiguous_taxa"],
            "review_queue_count": manifest["review_queue_count"],
            "duplicate_url_count": manifest["duplicate_url_count"],
            "conflicting_url_checksum_count": manifest["conflicting_url_checksum_count"],
            "duplicate_content_count": manifest["duplicate_content_count"],
            "taxonomy_staging_configured": manifest["taxonomy_staging_configured"],
            "artifact_registry_artifact_count": manifest["artifact_registry_artifact_count"],
            "staging_next_offset": int(checkpoint.get("next_offset", 0)),
            "staging_complete": bool(checkpoint.get("complete")),
            "projected_unique_rows": int(checkpoint.get("projected_unique_rows", 0)),
            "decision": "REVIEW_ONLY" if ready_for_review else "HOLD",
            "ready_for_review": ready_for_review,
            "ready_for_publication": False,
            "publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
