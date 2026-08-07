from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.calyx_orchestrator.artifact_registry import ArtifactRegistration
from app.calyx_orchestrator.brain_capture import (
    BrainCandidateRecord,
    BrainCaptureBundle,
    BrainRecordType,
)
from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import ExecutionReceipt, ExecutionState
from app.calyx_orchestrator.executor_registry import RegisteredExecutor
from app.calyx_orchestrator.review_eligibility import ReviewClass, ReviewRequest


@dataclass(frozen=True, slots=True)
class ExecutionEvidencePackage:
    artifact: ArtifactRegistration
    review: ReviewRequest
    capture: BrainCaptureBundle


def _stable_id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def _receipt_id(receipt: ExecutionReceipt) -> str:
    return _stable_id(
        "authoritative-execution",
        receipt.assignment_id,
        receipt.program_id,
        receipt.job_key,
        receipt.executor_key,
        receipt.input_checksum,
        receipt.output_checksum,
    )


def _canonical_receipt_payload(
    receipt: ExecutionReceipt,
    *,
    receipt_id: str,
    build_id: str,
    agent_id: str,
    registered_executor: RegisteredExecutor,
) -> dict[str, object]:
    return {
        "receipt_id": receipt_id,
        "assignment_id": receipt.assignment_id,
        "program_id": receipt.program_id,
        "job_key": receipt.job_key,
        "build_id": build_id,
        "agent_id": agent_id,
        "executor_key": receipt.executor_key,
        "executor_role_key": registered_executor.role_key,
        "state": receipt.state.value,
        "outcome": receipt.outcome.value,
        "input_checksum": receipt.input_checksum,
        "output_checksum": receipt.output_checksum,
        "output": dict(receipt.output),
        "evidence_uris": sorted(set(receipt.evidence_uris)),
        "authoritative": True,
        "external_side_effects": registered_executor.external_side_effects,
    }


def build_execution_evidence_package(
    receipt: ExecutionReceipt,
    *,
    registered_executor: RegisteredExecutor,
    build_id: str,
    agent_id: str,
    requested_by: str,
    producer_id: str,
    required_review_classes: tuple[ReviewClass, ...] = (ReviewClass.OPERATIONAL,),
) -> ExecutionEvidencePackage:
    """Translate verified authoritative Calyx execution into reviewed Brain candidate evidence."""

    receipt.verify()
    if not registered_executor.authoritative:
        raise PermissionError("NON_AUTHORITATIVE_EXECUTOR_EVIDENCE_PROHIBITED")
    if registered_executor.external_side_effects:
        raise PermissionError("EXTERNAL_SIDE_EFFECT_EXECUTOR_EVIDENCE_PROHIBITED")
    if receipt.executor_key != registered_executor.executor.executor_key:
        raise ValueError("EXECUTION_RECEIPT_EXECUTOR_MISMATCH")
    if receipt.state != ExecutionState.DELIVERED or receipt.outcome != TerminalOutcome.DELIVERED:
        raise ValueError("ONLY_AUTHORITATIVE_DELIVERED_RECEIPTS_ARE_EVIDENCE_ELIGIBLE")
    if not receipt.evidence_uris:
        raise ValueError("EXECUTION_EVIDENCE_URI_REQUIRED")
    if len(receipt.input_checksum) != 64 or len(receipt.output_checksum) != 64:
        raise ValueError("EXECUTION_CHECKSUM_REQUIRED")
    if not build_id.strip() or not agent_id.strip():
        raise ValueError("EXECUTION_BRAIN_IDENTITY_REQUIRED")
    if not requested_by.strip() or not producer_id.strip():
        raise ValueError("EXECUTION_REVIEW_ACTOR_REQUIRED")
    if requested_by == producer_id:
        raise PermissionError("EXECUTION_REVIEW_SELF_REQUEST_PROHIBITED")
    if not required_review_classes:
        raise ValueError("EXECUTION_REVIEW_CLASS_REQUIRED")
    if len(set(required_review_classes)) != len(required_review_classes):
        raise ValueError("DUPLICATE_EXECUTION_REVIEW_CLASS")

    receipt_id = _receipt_id(receipt)
    payload = _canonical_receipt_payload(
        receipt,
        receipt_id=receipt_id,
        build_id=build_id,
        agent_id=agent_id,
        registered_executor=registered_executor,
    )
    content = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    artifact_id = f"artifact:execution-receipt:{receipt_id}"
    artifact = ArtifactRegistration(
        artifact_id=artifact_id,
        content=content,
        media_type="application/json",
        source_uri=f"brain://execution-receipts/{receipt_id}",
        producer_assignment_id=receipt.assignment_id,
        evidence_uris=tuple(sorted(set(receipt.evidence_uris))),
        metadata={
            "build_id": build_id,
            "agent_id": agent_id,
            "program_id": receipt.program_id,
            "job_key": receipt.job_key,
            "executor_key": receipt.executor_key,
            "executor_role_key": registered_executor.role_key,
            "canonical_output_checksum": receipt.output_checksum,
            "authoritative": True,
            "candidate_only": True,
            "published": False,
        },
    )
    artifact.validate()

    review_request_id = _stable_id(
        "review",
        artifact_id,
        *(item.value for item in required_review_classes),
    )
    review = ReviewRequest(
        request_id=review_request_id,
        artifact_id=artifact_id,
        requested_by=requested_by,
        required_classes=required_review_classes,
        producer_id=producer_id,
    )
    review.validate()

    record = BrainCandidateRecord(
        record_id=f"validation:execution:{receipt_id}",
        record_type=BrainRecordType.VALIDATION,
        source_artifact_id=artifact_id,
        source_path=f"execution/{build_id}/{receipt_id}",
        source_checksum=artifact.checksum,
        payload={
            "build_id": build_id,
            "assignment_id": receipt.assignment_id,
            "program_id": receipt.program_id,
            "job_key": receipt.job_key,
            "agent_id": agent_id,
            "receipt_id": receipt_id,
            "executor_key": receipt.executor_key,
            "executor_role_key": registered_executor.role_key,
            "outcome": receipt.outcome.value,
            "output_checksum": receipt.output_checksum,
            "evidence_uris": list(artifact.evidence_uris),
            "review_required": [item.value for item in required_review_classes],
            "authoritative": True,
            "candidate_only": True,
            "published": False,
        },
    )
    capture = BrainCaptureBundle(
        bundle_id=_stable_id("capture", receipt_id, artifact.checksum),
        review_request_id=review.request_id,
        records=(record,),
    )
    return ExecutionEvidencePackage(artifact=artifact, review=review, capture=capture)
