"""Review-only taxonomy release intake and bounded staging for CALYX issue #461.

This module accepts a caller-supplied taxonomy export, preserves it immutably by
content digest, reuses the existing non-publishing taxonomy preflight validator,
normalizes records into an evidence bundle, builds an unresolved-review queue,
and projects normalized rows into a bounded local staging artifact.

It deliberately has no production database, Knowledge Graph, taxonomy activation,
or publication capability. A successful intake can become ready for *review*;
it can never become ready for promotion from this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.taxonomy_preflight import (
    Policy,
    load_csv,
    normalize,
    scientific_name,
    taxon_key,
    validate,
)

INTAKE_SCHEMA_VERSION = "1.1.0"
RELEASE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


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


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("a valid source filename is required")
    return RELEASE_ID_RE.sub("_", name)[:180]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _row_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _first(row: dict[str, str], *names: str) -> str:
    folded = {key.casefold(): value for key, value in row.items()}
    for name in names:
        if value := normalize(folded.get(name.casefold(), "")):
            return value
    return ""


def _status(row: dict[str, str]) -> str:
    raw = _first(row, "taxonomic_status", "status", "accepted_status", "record_type")
    value = raw.casefold()
    if value in {"accepted", "accepted name", "a", "s", "species"}:
        return "accepted"
    if "syn" in value or value in {"synonym", "basionym"}:
        return "synonym"
    return value or "unresolved"


def _malformed_count(finding_counts: dict[str, int]) -> int:
    return sum(
        count
        for key, count in finding_counts.items()
        if key.endswith(":malformed_taxon_name")
    )


@dataclass(frozen=True)
class ReleaseIdentity:
    release_id: str
    filename: str
    sha256: str
    byte_count: int
    expected_label: str | None


class TaxonomyReleaseIntakeService:
    """Filesystem-backed, deterministic and review-only release workspace."""

    def __init__(self, workspace: Path, *, maximum_bytes: int = 100 * 1024 * 1024) -> None:
        self.workspace = workspace
        self.maximum_bytes = maximum_bytes

    def _release_dir(self, release_id: str) -> Path:
        if not release_id or RELEASE_ID_RE.sub("_", release_id) != release_id:
            raise ValueError("invalid release_id")
        return self.workspace / "releases" / release_id

    def intake_bytes(
        self,
        filename: str,
        content: bytes,
        *,
        expected_label: str | None = None,
        baseline_path: Path | None = None,
        policy: Policy | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("taxonomy source file is empty")
        if len(content) > self.maximum_bytes:
            raise ValueError(f"taxonomy source exceeds maximum_bytes={self.maximum_bytes}")
        if baseline_path is not None and not baseline_path.is_file():
            raise ValueError("configured taxonomy baseline is not a regular file")

        clean_name = _safe_filename(filename)
        digest = _sha256(content)
        release_id = f"rel-{digest[:20]}"
        root = self._release_dir(release_id)
        source = root / "source" / clean_name
        if source.exists():
            if source.read_bytes() != content:
                raise RuntimeError("immutable release source digest collision")
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".taxonomy-source.", dir=source.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, source)
            except Exception:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                raise

        identity = ReleaseIdentity(
            release_id=release_id,
            filename=clean_name,
            sha256=digest,
            byte_count=len(content),
            expected_label=normalize(expected_label) or None,
        )
        preflight = validate(source, baseline_path=baseline_path, policy=policy)
        columns, rows, *_ = load_csv(source)
        normalized_rows: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        for index, row in enumerate(rows, start=1):
            name = scientific_name(row)
            key = taxon_key(row)
            status = _status(row)
            status_counts[status] += 1
            normalized_row = {
                "row_number": index,
                "taxon_key": key,
                "scientific_name": name,
                "taxonomic_status": status,
                "accepted_name_id": _first(row, "accepted_name_id", "acceptednameid"),
                "source_record": {column: normalize(row.get(column)) for column in columns},
            }
            normalized_row["row_sha256"] = _row_digest(normalized_row)
            normalized_rows.append(normalized_row)
            reason = None
            if key == "name:" or not name:
                reason = "missing_taxon_identity"
            elif status == "synonym" and not normalized_row["accepted_name_id"]:
                reason = "synonym_missing_accepted_name_id"
            elif status == "unresolved":
                reason = "unresolved_taxonomic_status"
            if reason:
                unresolved.append(
                    {
                        "row_number": index,
                        "taxon_key": key,
                        "scientific_name": name,
                        "reason": reason,
                        "row_sha256": normalized_row["row_sha256"],
                        "review_state": "pending",
                    }
                )

        normalized_text = "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in normalized_rows
        )
        normalized_sha = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        status_payload = dict(sorted(status_counts.items()))
        malformed_count = _malformed_count(preflight.finding_counts)
        _atomic_write(root / "normalized.jsonl", normalized_text)
        _json(root / "preflight.json", preflight.to_dict())
        _json(root / "review_queue.json", unresolved)
        _json(
            root / "manifest.json",
            {
                "schema_version": INTAKE_SCHEMA_VERSION,
                "identity": asdict(identity),
                "baseline_filename": preflight.baseline_filename,
                "baseline_sha256": preflight.baseline_sha256,
                "preflight_status": preflight.status,
                "preflight_run_id": preflight.run_id,
                "preflight_metrics": preflight.metrics,
                "preflight_finding_counts": preflight.finding_counts,
                "normalized_row_count": len(normalized_rows),
                "normalized_sha256": normalized_sha,
                "status_counts": status_payload,
                "accepted_name_count": status_payload.get("accepted", 0),
                "synonym_count": status_payload.get("synonym", 0),
                "malformed_taxon_count": malformed_count,
                "unresolved_review_count": len(unresolved),
                "comparison": preflight.diff,
                "taxonomy_activation_authorized": False,
                "production_relink_authorized": False,
                "knowledge_graph_publication_authorized": False,
            },
        )
        if not (root / "staging_checkpoint.json").exists():
            _json(root / "staging_checkpoint.json", {"next_offset": 0, "complete": False})
        return self.readiness(release_id)

    def project_staging(self, release_id: str, *, batch_size: int = 500) -> dict[str, Any]:
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        root = self._release_dir(release_id)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        rows = [
            json.loads(line)
            for line in (root / "normalized.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checkpoint_path = root / "staging_checkpoint.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        offset = int(checkpoint.get("next_offset", 0))
        if checkpoint.get("complete"):
            return self.readiness(release_id)

        end = min(offset + batch_size, len(rows))
        staging_path = root / "staging.jsonl"
        existing: dict[str, dict[str, Any]] = {}
        if staging_path.exists():
            for line in staging_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    existing[record["row_sha256"]] = record
        for row in rows[offset:end]:
            existing.setdefault(row["row_sha256"], row)
        ordered = sorted(existing.values(), key=lambda item: (item["row_number"], item["row_sha256"]))
        _atomic_write(
            staging_path,
            "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in ordered),
        )
        complete = end >= len(rows)
        _json(
            checkpoint_path,
            {
                "next_offset": end,
                "complete": complete,
                "normalized_sha256": manifest["normalized_sha256"],
                "projected_unique_rows": len(ordered),
            },
        )
        return self.readiness(release_id)

    def review_queue(self, release_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        root = self._release_dir(release_id)
        queue_path = root / "review_queue.json"
        if not queue_path.exists():
            raise FileNotFoundError(f"unknown taxonomy release: {release_id}")
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        return {
            "release_id": release_id,
            "total": len(queue),
            "offset": offset,
            "limit": limit,
            "items": queue[offset : offset + limit],
            "review_write_authorized": False,
        }

    def readiness(self, release_id: str) -> dict[str, Any]:
        root = self._release_dir(release_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown taxonomy release: {release_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint = json.loads((root / "staging_checkpoint.json").read_text(encoding="utf-8"))
        unresolved = json.loads((root / "review_queue.json").read_text(encoding="utf-8"))
        preflight_ok = manifest["preflight_status"] in {"PASS", "WARN"}
        staging_complete = bool(checkpoint.get("complete"))
        ready_for_review = preflight_ok and staging_complete
        return {
            "schema_version": INTAKE_SCHEMA_VERSION,
            "release_id": release_id,
            "identity": manifest["identity"],
            "source_sha256": manifest["identity"]["sha256"],
            "baseline_filename": manifest.get("baseline_filename"),
            "baseline_sha256": manifest.get("baseline_sha256"),
            "preflight_status": manifest["preflight_status"],
            "preflight_run_id": manifest["preflight_run_id"],
            "normalized_row_count": manifest["normalized_row_count"],
            "normalized_sha256": manifest["normalized_sha256"],
            "status_counts": manifest["status_counts"],
            "accepted_name_count": manifest["accepted_name_count"],
            "synonym_count": manifest["synonym_count"],
            "malformed_taxon_count": manifest["malformed_taxon_count"],
            "comparison": manifest.get("comparison"),
            "unresolved_review_count": len(unresolved),
            "staging_next_offset": int(checkpoint.get("next_offset", 0)),
            "staging_complete": staging_complete,
            "decision": "REVIEW_ONLY" if ready_for_review else "HOLD",
            "ready_for_review": ready_for_review,
            "ready_for_promotion": False,
            "taxonomy_activation_authorized": False,
            "production_relink_authorized": False,
            "knowledge_graph_publication_authorized": False,
        }
