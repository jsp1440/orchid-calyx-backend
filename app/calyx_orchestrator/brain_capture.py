from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .artifact_registry import ImmutableArtifactRegistry
from .review_eligibility import ReviewRegistry


class BrainRecordType(StrEnum):
    VALIDATION = "validation"
    OBSERVATION = "observation"
    INFERENCE = "inference"


@dataclass(frozen=True, slots=True)
class BrainCandidateRecord:
    record_id: str
    record_type: BrainRecordType
    source_artifact_id: str
    source_path: str
    source_checksum: str
    payload: dict[str, Any]

    def validate(self) -> None:
        if not self.record_id.strip():
            raise ValueError("BRAIN_RECORD_ID_REQUIRED")
        if not self.source_artifact_id.strip():
            raise ValueError("BRAIN_RECORD_SOURCE_ARTIFACT_REQUIRED")
        if not self.source_checksum.strip():
            raise ValueError("BRAIN_RECORD_SOURCE_CHECKSUM_REQUIRED")


@dataclass(frozen=True, slots=True)
class BrainCaptureBundle:
    bundle_id: str
    review_request_id: str
    records: tuple[BrainCandidateRecord, ...]

    def validate(self) -> None:
        if not self.bundle_id.strip():
            raise ValueError("BRAIN_BUNDLE_ID_REQUIRED")
        if not self.review_request_id.strip():
            raise ValueError("BRAIN_BUNDLE_REVIEW_REQUEST_REQUIRED")
        if not self.records:
            raise ValueError("BRAIN_BUNDLE_RECORDS_REQUIRED")
        for record in self.records:
            record.validate()


@dataclass(slots=True)
class BrainCandidateStore:
    _bundles: list[dict[str, Any]] = field(default_factory=list)

    def capture(
        self,
        bundle: BrainCaptureBundle,
        *,
        artifacts: ImmutableArtifactRegistry,
        reviews: ReviewRegistry,
    ) -> BrainCaptureBundle:
        bundle.validate()
        eligibility = reviews.eligibility(bundle.review_request_id)
        if not eligibility.eligible:
            raise PermissionError("CAPTURE_REVIEW_NOT_ELIGIBLE")
        for record in bundle.records:
            artifacts.require(record.source_artifact_id)
        self._bundles.append(
            {
                "bundle_id": bundle.bundle_id,
                "review_request_id": bundle.review_request_id,
                "record_count": len(bundle.records),
                "published": False,
                "candidate_only": True,
            }
        )
        return bundle

    def status(self) -> dict[str, object]:
        return {"bundle_count": len(self._bundles), "bundles": list(self._bundles)}
