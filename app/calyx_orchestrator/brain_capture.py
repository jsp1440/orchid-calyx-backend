from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .artifact_registry import ImmutableArtifactRegistry
from .review_eligibility import ReviewRegistry


class BrainRecordType(StrEnum):
    BUILD = "build"
    VALIDATION = "validation"
    ARTIFACT = "artifact"
    DEPENDENCY = "dependency"
    RISK = "risk"
    DECISION = "decision"


@dataclass(frozen=True, slots=True)
class BrainCandidateRecord:
    record_id: str
    record_type: BrainRecordType
    source_artifact_id: str
    source_path: str
    source_checksum: str
    payload: dict[str, object]

    @property
    def checksum(self) -> str:
        encoded = json.dumps(
            {
                "record_id": self.record_id,
                "record_type": self.record_type.value,
                "source_artifact_id": self.source_artifact_id,
                "source_path": self.source_path,
                "source_checksum": self.source_checksum,
                "payload": self.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class BrainCaptureBundle:
    bundle_id: str
    review_request_id: str
    records: tuple[BrainCandidateRecord, ...]

    @property
    def checksum(self) -> str:
        encoded = "|".join(record.checksum for record in self.records).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class BrainCandidateStore:
    """Atomic, immutable store for reviewed Brain candidate bundles."""

    def __init__(self) -> None:
        self._bundles: dict[str, BrainCaptureBundle] = {}
        self._record_checksums: dict[str, str] = {}

    def capture(
        self,
        bundle: BrainCaptureBundle,
        *,
        artifacts: ImmutableArtifactRegistry,
        reviews: ReviewRegistry,
    ) -> BrainCaptureBundle:
        if not bundle.bundle_id.strip() or not bundle.records:
            raise ValueError("CAPTURE_BUNDLE_INVALID")
        eligibility = reviews.eligibility(bundle.review_request_id)
        if not eligibility.eligible:
            raise PermissionError("CAPTURE_REVIEW_NOT_ELIGIBLE")
        if any(record.source_artifact_id != eligibility.artifact_id for record in bundle.records):
            raise ValueError("CAPTURE_ARTIFACT_REVIEW_MISMATCH")

        staged: dict[str, str] = {}
        for record in bundle.records:
            artifact = artifacts.require_evidence(record.source_artifact_id)
            if artifact.checksum != record.source_checksum:
                raise ValueError("CAPTURE_SOURCE_CHECKSUM_MISMATCH")
            if not record.record_id.strip() or not record.source_path.strip():
                raise ValueError("CAPTURE_RECORD_INVALID")
            if record.record_id in staged and staged[record.record_id] != record.checksum:
                raise ValueError("CAPTURE_DUPLICATE_RECORD_CONFLICT")
            existing = self._record_checksums.get(record.record_id)
            if existing is not None and existing != record.checksum:
                raise ValueError("IMMUTABLE_BRAIN_RECORD_CONFLICT")
            staged[record.record_id] = record.checksum

        existing_bundle = self._bundles.get(bundle.bundle_id)
        if existing_bundle is not None:
            if existing_bundle != bundle:
                raise ValueError("IMMUTABLE_CAPTURE_BUNDLE_CONFLICT")
            return existing_bundle

        self._record_checksums.update(staged)
        self._bundles[bundle.bundle_id] = bundle
        return bundle

    def rollback(self, bundle_id: str) -> BrainCaptureBundle:
        try:
            bundle = self._bundles.pop(bundle_id)
        except KeyError as exc:
            raise LookupError("CAPTURE_BUNDLE_NOT_FOUND") from exc
        remaining_record_ids = {
            record.record_id
            for remaining in self._bundles.values()
            for record in remaining.records
        }
        for record in bundle.records:
            if record.record_id not in remaining_record_ids:
                self._record_checksums.pop(record.record_id, None)
        return bundle

    def status(self) -> dict[str, object]:
        return {
            "bundle_count": len(self._bundles),
            "record_count": len(self._record_checksums),
            "bundles": [
                {
                    "bundle_id": bundle.bundle_id,
                    "review_request_id": bundle.review_request_id,
                    "checksum": bundle.checksum,
                    "record_count": len(bundle.records),
                    "candidate_only": True,
                    "published": False,
                }
                for bundle in sorted(self._bundles.values(), key=lambda item: item.bundle_id)
            ],
        }
