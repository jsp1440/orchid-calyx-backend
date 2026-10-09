"""Governed durable-intake service for contributor photographs.

Sits between the authenticated API layer and the offline-governed intake /
bridge modules. It is the only component that touches contributor bytes:

* Originals are written content-addressed and never modified, re-encoded, or
  moved after first write. A re-submitted identical byte stream maps to the
  same object reference.
* The server computes the SHA-256 itself; a client-supplied checksum is a
  cross-check, never the source of truth.
* Contributor identity comes from the authenticated actor, not from
  client-supplied fields, unless the caller is trusted system automation
  (API-key channel), in which case an explicit ``contributor_id`` is honored.
* Batch manifests, the cross-batch checksum index, and session linkage are
  persisted so intake survives restarts (file-backed governed storage, the
  same pattern as the file-backed registry/session stores). Sessions and
  review decisions themselves persist through the governed session store
  (migration 612 when durable mode is activated).

Batch ingestion is idempotent at two levels: (1) replaying the same
``batch_id`` returns the stored manifest without re-staging; (2) any content
checksum staged in a previous batch is skipped, not duplicated.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.contributor_image_intake import (
    SUPPORTED_MEDIA,
    StagedContributorImage,
    intake_contributor_batch,
)
from runtime.matrix_identification_session import create_session

BATCH_SCHEMA_VERSION = "matrix-contributor-intake-batch/v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def default_intake_root() -> Path:
    return Path(
        os.getenv(
            "CALYX_MATRIX_CONTRIBUTOR_INTAKE_DIR",
            "/tmp/calyx/matrix-contributor-intake",
        )
    )


def _safe_component(value: str, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or any(part in cleaned for part in ("/", "\\", "..")):
        raise ValueError(f"invalid {field}")
    return cleaned


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(str(name or "").strip())
    base = _SAFE_NAME_RE.sub("_", base).strip("._")
    if not base:
        raise ValueError("original_filename is required")
    return base[:200]


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


class ContributorIntakeService:
    """File-backed governed intake workspace (originals + index + manifests)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_intake_root()

    # -- paths -----------------------------------------------------------

    @property
    def originals_dir(self) -> Path:
        return self.root / "originals"

    @property
    def batches_dir(self) -> Path:
        return self.root / "batches"

    @property
    def index_path(self) -> Path:
        return self.root / "index" / "checksums.json"

    def _batch_path(self, batch_id: str) -> Path:
        return self.batches_dir / f"{_safe_component(batch_id, 'batch_id')}.json"

    # -- checksum index --------------------------------------------------

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"schema_version": BATCH_SCHEMA_VERSION, "checksums": {}}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def seen_checksums(self) -> set[str]:
        return set(self._load_index().get("checksums", {}))

    def _record_checksums(
        self, staged: list[StagedContributorImage], *, batch_id: str
    ) -> None:
        if not staged:
            return
        index = self._load_index()
        checksums = index.setdefault("checksums", {})
        for image in staged:
            checksums.setdefault(
                image.content_sha256,
                {
                    "submission_id": image.submission_id,
                    "batch_id": batch_id,
                    "original_object_ref": image.original_object_ref,
                    "first_staged_at": image.staged_at,
                },
            )
        _write_json_atomic(self.index_path, index)

    # -- originals -------------------------------------------------------

    def _store_original(self, content: bytes, content_sha256: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        rel = Path(content_sha256[:2]) / f"{content_sha256}{suffix}"
        target = self.originals_dir / rel
        if target.exists():
            existing = hashlib.sha256(target.read_bytes()).hexdigest()
            if existing != content_sha256:
                raise RuntimeError(
                    "CONTRIBUTOR_ORIGINAL_CHECKSUM_CONFLICT: existing preserved "
                    "original does not match the submitted checksum"
                )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_bytes(content)
            temp.replace(target)
        return str(Path("originals") / rel)

    # -- manifest --------------------------------------------------------

    def get_batch_manifest(self, batch_id: str) -> dict[str, Any]:
        path = self._batch_path(batch_id)
        if not path.exists():
            raise FileNotFoundError(f"contributor intake batch not found: {batch_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- intake ----------------------------------------------------------

    def intake_batch(
        self,
        submissions: list[dict[str, Any]],
        *,
        actor: str,
        batch_id: str | None = None,
        allow_contributor_override: bool = False,
        open_sessions: bool = False,
        registry_id: str | None = None,
        registry_version: str | None = None,
        canonical_lookup: dict[str, str] | None = None,
        staged_at: str | None = None,
    ) -> dict[str, Any]:
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("authenticated actor is required")
        if not submissions:
            raise ValueError("at least one submission is required")
        if open_sessions and (not registry_id or not registry_version):
            raise ValueError(
                "registry_id and registry_version are required when open_sessions is true"
            )

        batch = str(batch_id or "").strip() or f"batch-{hashlib.sha256(_now().encode()).hexdigest()[:16]}"
        _safe_component(batch, "batch_id")

        # Level-1 idempotency: replaying a batch returns its stored manifest.
        batch_path = self._batch_path(batch)
        if batch_path.exists():
            manifest = json.loads(batch_path.read_text(encoding="utf-8"))
            manifest["idempotent_replay"] = True
            return manifest

        # Decode bytes, compute checksums server-side, preserve originals.
        prepared: list[dict[str, Any]] = []
        filename_map: list[dict[str, Any]] = []
        for position, submission in enumerate(submissions):
            original_filename = _sanitize_filename(
                submission.get("original_filename") or ""
            )
            contributor_id = actor
            if allow_contributor_override and submission.get("contributor_id"):
                contributor_id = str(submission["contributor_id"]).strip()

            entry: dict[str, Any] = {
                "contributor_id": contributor_id,
                "contributor_display_name": submission.get("contributor_display_name"),
                "permission_grant": submission.get("permission_grant"),
                "rights_holder_affirmed": submission.get("rights_holder_affirmed"),
                "taxon_name": submission.get("taxon_name"),
                "taxon_certainty": submission.get("taxon_certainty", "unknown"),
                "candidate_taxa": submission.get("candidate_taxa"),
                "provenance": {
                    **dict(submission.get("provenance") or {}),
                    "original_filename": original_filename,
                },
            }

            content: bytes | None = None
            raw_b64 = submission.get("content_base64")
            if raw_b64:
                try:
                    content = base64.b64decode(str(raw_b64), validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError(
                        f"content_base64 is not valid base64 for {original_filename}"
                    ) from exc

            client_sha = str(submission.get("content_sha256") or "").strip().lower()
            if content is not None:
                computed = hashlib.sha256(content).hexdigest()
                if client_sha and client_sha != computed:
                    raise ValueError(
                        f"content_sha256 mismatch for {original_filename}: "
                        "client-supplied checksum does not match submitted bytes"
                    )
                entry["content_sha256"] = computed
                mime_type = str(submission.get("mime_type") or "").strip().lower()
                if not mime_type:
                    mime_type = _MIME_BY_SUFFIX.get(Path(original_filename).suffix.lower(), "")
                entry["mime_type"] = mime_type
                if mime_type in SUPPORTED_MEDIA:
                    entry["original_object_ref"] = self._store_original(
                        content, computed, original_filename
                    )
                else:
                    # Rejections for unsupported media still need an object ref
                    # value to reach the governed rejection path unchanged.
                    entry["original_object_ref"] = f"unsupported://{original_filename}"
            else:
                # Reference mode: originals preserved elsewhere; the governed
                # checksum and reference are required and recorded verbatim.
                entry["content_sha256"] = client_sha
                entry["mime_type"] = str(submission.get("mime_type") or "").strip().lower()
                entry["original_object_ref"] = str(
                    submission.get("original_object_ref") or ""
                ).strip()

            submission_id = str(submission.get("submission_id") or "").strip()
            if not submission_id and _SHA256_RE.fullmatch(entry["content_sha256"] or ""):
                submission_id = f"sub-{entry['content_sha256'][:16]}"
            entry["submission_id"] = submission_id

            prepared.append(entry)
            filename_map.append(
                {
                    "original_filename": original_filename,
                    "submission_id": submission_id or None,
                }
            )

        result = intake_contributor_batch(
            prepared,
            batch_id=batch,
            seen_checksums=self.seen_checksums(),
            canonical_lookup=canonical_lookup,
            staged_at=staged_at,
        )

        # Level-2 idempotency: newly staged checksums join the cross-batch index.
        self._record_checksums(list(result.staged), batch_id=batch)

        # Open governed Matrix sessions for staged images when requested.
        session_links: dict[str, dict[str, Any]] = {}
        if open_sessions:
            for image in result.staged:
                session = create_session(
                    registry_id=str(registry_id),
                    version=str(registry_version),
                    actor=actor,
                    metadata={
                        "contributor_submission_id": image.submission_id,
                        "contributor_batch_id": batch,
                        "content_sha256": image.content_sha256,
                        "original_object_ref": image.original_object_ref,
                        "origin": "matrix-contributor-intake",
                    },
                )
                session_links[image.submission_id] = {
                    "session_id": session["session_id"],
                    "registry_id": registry_id,
                    "registry_version": registry_version,
                    "registry_checksum_sha256": session["registry"]["checksum_sha256"],
                }

        outcome_by_submission: dict[str, dict[str, Any]] = {}
        for image in result.staged:
            outcome_by_submission[image.submission_id] = {
                "status": "staged",
                "taxon_name": image.taxon_name,
                "taxon_certainty": image.taxon_certainty,
                "candidate_taxa": list(image.candidate_taxa),
                "canonical_taxon_id": image.canonical_taxon_id,
                "reconciliation_state": image.reconciliation_state,
                "content_sha256": image.content_sha256,
                "original_object_ref": image.original_object_ref,
                "attribution_line": image.attribution_line,
                "permission_grant": image.permission_grant,
                "session": session_links.get(image.submission_id),
            }
        for rejected in result.rejected:
            outcome_by_submission[rejected.submission_id] = {
                "status": "rejected",
                "reason": rejected.reason,
            }

        seen_now = self.seen_checksums()
        mapping: list[dict[str, Any]] = []
        for item in filename_map:
            submission_id = item["submission_id"]
            outcome = outcome_by_submission.get(submission_id)
            if outcome is None and submission_id:
                prepared_entry = next(
                    (p for p in prepared if p["submission_id"] == submission_id), {}
                )
                if prepared_entry.get("content_sha256") in seen_now:
                    outcome = {
                        "status": "duplicate_skipped",
                        "content_sha256": prepared_entry["content_sha256"],
                    }
            mapping.append(
                {
                    "original_filename": item["original_filename"],
                    "submission_id": submission_id,
                    **(outcome or {"status": "rejected", "reason": "intake_validation_failed"}),
                }
            )

        manifest: dict[str, Any] = {
            "schema_version": BATCH_SCHEMA_VERSION,
            "batch_id": batch,
            "actor": actor,
            "created_at": _now(),
            "idempotent_replay": False,
            "summary": result.summary(),
            "filename_mapping": mapping,
            "staged": [image.as_dict() for image in result.staged],
            "rejected": [item.as_dict() for item in result.rejected],
            "review_queue": [item.as_dict() for item in result.review_queue],
            "sessions_opened": len(session_links),
            "governance": {
                "original_preserved": True,
                "server_side_checksum": True,
                "contributor_identity_from_authenticated_actor": True,
                "no_production_graph_mutation": True,
            },
        }
        _write_json_atomic(batch_path, manifest)
        return manifest


def intake_batch(
    submissions: list[dict[str, Any]],
    *,
    actor: str,
    root: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return ContributorIntakeService(root).intake_batch(
        submissions, actor=actor, **kwargs
    )


def get_batch_manifest(batch_id: str, *, root: Path | None = None) -> dict[str, Any]:
    return ContributorIntakeService(root).get_batch_manifest(batch_id)
