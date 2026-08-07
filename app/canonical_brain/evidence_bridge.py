from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.calyx_orchestrator.brain_capture import (
    BrainCandidateRecord,
    BrainCaptureBundle,
    BrainRecordType,
)

from app.calyx_orchestrator.artifact_registry import ArtifactRegistration
from app.calyx_orchestrator.review_eligibility import ReviewClass, ReviewRequest

from .orchestration import ExecutionReceipt


@dataclass(frozen=True, slots=True)
class ExecutionEvidencePackage:
    artifact: ArtifactRegistration
    review: ReviewRequest
    capture: BrainCaptureBundle


def _stable_id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def _canonical_receipt_payload(receipt: ExecutionReceipt) -> dict[str, object]:
    return {
        "receipt_id": receipt.receipt_id,
        "assignment_id": receipt.assignment_id,
        "build_id": receipt.build_id,
        "agent_id": receipt.agent_id,
        "outcome": receipt.outcome,
        "recorded_at": receipt.recorded_at.isoformat(),
        "evidence_uris": sorted(set(receipt.evidence_uris)),
        "output_checksum": receipt.output_checksum,
    }


def build_execution_evidence_package(
    receipt: ExecutionReceipt,
    *,
    requested_by: str,
    producer_id: str,
    required_review_classes: tuple[ReviewClass, ...] = (ReviewClass.OPERATIONAL,),
) -> ExecutionEvidencePackage:
    if receipt.outcome != "completed":
        raise ValueError("ONLY_COMPLETED_RECEIPTS_ARE_EVIDENCE_ELIGIBLE")
    if not receipt.evidence_uris:
        raise ValueError("EXECUTION_EVIDENCE_URI_REQUIRED")
    if receipt.output_checksum is None or len(receipt.output_checksum) != 64:
        raise ValueError("EXECUTION_OUTPUT_CHECKSUM_REQUIRED")
    if not requested_by.strip() or not producer_id.strip():
        raise ValueError("EXECUTION_REVIEW_ACTOR_REQUIRED")
    if requested_by == producer_id:
        raise PermissionError("EXECUTION_REVIEW_SELF_REQUEST_PROHIBITED")
    if not required_review_classes:
        raise ValueError("EXECUTION_REVIEW_CLASS_REQUIRED")
    if len(set(required_review_classes)) != len(required_review_classes):
        raise ValueError("DUPLICATE_EXECUTION_REVIEW_CLASS")

    payload = _canonical_receipt_payload(receipt)
    content = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    artifact_id = f"artifact:execution-receipt:{receipt.receipt_id}"
    artifact = ArtifactRegistration(
        artifact_id=artifact_id,
        content=content,
        media_type="application/json",
        source_uri=f"brain://execution-receipts/{receipt.receipt_id}",
        producer_assignment_id=receipt.assignment_id,
        evidence_uris=tuple(sorted(set(receipt.evidence_uris))),
        metadata={
            "build_id": receipt.build_id,
            "agent_id": receipt.agent_id,
            "canonical_output_checksum": receipt.output_checksum,
            "candidate_only": True,
            "published": False,
        },
    )
    artifact.validate()

    review_request_id = _stable_id("review", artifact_id, *(item.value for item in required_review_classes))
    review = ReviewRequest(
        request_id=review_request_id,
        artifact_id=artifact_id,
        requested_by=requested_by,
        required_classes=required_review_classes,
        producer_id=producer_id,
    )
    review.validate()

    record = BrainCandidateRecord(
        record_id=f"validation:execution:{receipt.receipt_id}",
        record_type=BrainRecordType.VALIDATION,
        source_artifact_id=artifact_id,
        source_path=f"execution/{receipt.build_id}/{receipt.receipt_id}",
        source_checksum=artifact.checksum,
        payload={
            "build_id": receipt.build_id,
            "assignment_id": receipt.assignment_id,
            "agent_id": receipt.agent_id,
            "receipt_id": receipt.receipt_id,
            "outcome": receipt.outcome,
            "output_checksum": receipt.output_checksum,
            "evidence_uris": list(artifact.evidence_uris),
            "review_required": [item.value for item in required_review_classes],
            "candidate_only": True,
            "published": False,
        },
    )
    capture = BrainCaptureBundle(
        bundle_id=_stable_id("capture", receipt.receipt_id, artifact.checksum),
        review_request_id=review.request_id,
        records=(record,),
    )
    return ExecutionEvidencePackage(artifact=artifact, review=review, capture=capture)
