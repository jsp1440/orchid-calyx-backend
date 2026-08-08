from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import utcnow
from .sandbox_supervisor_evidence import (
    SupervisorValidationReceipt,
    ValidationRequestEnvelope,
)
from .sandbox_supervisor_models import SandboxValidationRequestRecord


class SandboxSupervisorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_request(
        self,
        *,
        owner: str,
        program_job_id: str | None,
        repository: str,
        branch: str,
        checkout_commit_sha: str,
        preset: str,
        targets: list[dict[str, str]],
        timeout_seconds: int,
    ) -> SandboxValidationRequestRecord:
        envelope = ValidationRequestEnvelope.build(
            repository=repository,
            branch=branch,
            checkout_commit_sha=checkout_commit_sha,
            preset=preset,
            targets=targets,
            timeout_seconds=timeout_seconds,
        )
        existing = self.db.scalar(
            select(SandboxValidationRequestRecord).where(
                SandboxValidationRequestRecord.request_digest == envelope.request_digest
            )
        )
        if existing is not None:
            if existing.owner != owner:
                raise PermissionError("SANDBOX_VALIDATION_REQUEST_DIGEST_CONFLICT")
            return existing
        record = SandboxValidationRequestRecord(
            owner=owner,
            program_job_id=program_job_id,
            repository=envelope.repository,
            branch=envelope.branch,
            checkout_commit_sha=envelope.checkout_commit_sha,
            preset=envelope.preset,
            targets_json=json.dumps([item.as_dict() for item in envelope.targets], sort_keys=True),
            timeout_seconds=envelope.timeout_seconds,
            request_digest=envelope.request_digest,
            status="queued",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def claim_next(self, *, worker_id: str) -> SandboxValidationRequestRecord | None:
        worker = worker_id.strip()
        if not worker:
            raise ValueError("SANDBOX_SUPERVISOR_WORKER_REQUIRED")
        record = self.db.scalar(
            select(SandboxValidationRequestRecord)
            .where(SandboxValidationRequestRecord.status == "queued")
            .order_by(SandboxValidationRequestRecord.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        if record is None:
            return None
        record.status = "claimed"
        record.claim_worker = worker
        record.claim_token = str(uuid4())
        record.claimed_at = utcnow()
        self.db.commit()
        self.db.refresh(record)
        return record

    def complete(
        self,
        *,
        request_id: str,
        worker_id: str,
        claim_token: str,
        receipt_payload: dict,
    ) -> SandboxValidationRequestRecord:
        record = self.db.get(SandboxValidationRequestRecord, request_id)
        if record is None:
            raise LookupError("SANDBOX_VALIDATION_REQUEST_NOT_FOUND")
        if record.status != "claimed":
            raise ValueError("SANDBOX_VALIDATION_REQUEST_NOT_CLAIMED")
        if record.claim_worker != worker_id or record.claim_token != claim_token:
            raise PermissionError("SANDBOX_VALIDATION_CLAIM_MISMATCH")
        envelope = self._envelope(record)
        receipt = SupervisorValidationReceipt.from_mapping(receipt_payload)
        receipt.verify_for(envelope)
        record.authorization_id = receipt.authorization_id
        record.policy_digest = receipt.policy_digest
        record.evidence_uri = receipt.evidence_uri
        record.outcome = receipt.outcome
        record.receipt_digest = receipt.receipt_digest
        record.result_json = json.dumps(receipt.payload(), sort_keys=True, separators=(",", ":"))
        record.status = "completed" if receipt.outcome == "delivered" else "blocked"
        record.completed_at = utcnow()
        record.claim_token = None
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_owned(self, *, owner: str, request_id: str) -> SandboxValidationRequestRecord:
        record = self.db.get(SandboxValidationRequestRecord, request_id)
        if record is None or record.owner != owner:
            raise LookupError("SANDBOX_VALIDATION_REQUEST_NOT_FOUND")
        return record

    @staticmethod
    def public_snapshot(record: SandboxValidationRequestRecord) -> dict:
        return {
            "request_id": record.request_id,
            "program_job_id": record.program_job_id,
            "repository": record.repository,
            "branch": record.branch,
            "checkout_commit_sha": record.checkout_commit_sha,
            "preset": record.preset,
            "targets": json.loads(record.targets_json),
            "timeout_seconds": record.timeout_seconds,
            "request_digest": record.request_digest,
            "status": record.status,
            "authorization_id": record.authorization_id,
            "policy_digest": record.policy_digest,
            "evidence_uri": record.evidence_uri,
            "outcome": record.outcome,
            "receipt_digest": record.receipt_digest,
            "claimed": record.claim_worker is not None,
            "claim_token_exposed": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @staticmethod
    def supervisor_claim_snapshot(record: SandboxValidationRequestRecord) -> dict:
        return {
            "request_id": record.request_id,
            "repository": record.repository,
            "branch": record.branch,
            "checkout_commit_sha": record.checkout_commit_sha,
            "preset": record.preset,
            "targets": json.loads(record.targets_json),
            "timeout_seconds": record.timeout_seconds,
            "request_digest": record.request_digest,
            "claim_worker": record.claim_worker,
            "claim_token": record.claim_token,
        }

    @staticmethod
    def _envelope(record: SandboxValidationRequestRecord) -> ValidationRequestEnvelope:
        return ValidationRequestEnvelope.build(
            repository=record.repository,
            branch=record.branch,
            checkout_commit_sha=record.checkout_commit_sha,
            preset=record.preset,
            targets=json.loads(record.targets_json),
            timeout_seconds=record.timeout_seconds,
        )
