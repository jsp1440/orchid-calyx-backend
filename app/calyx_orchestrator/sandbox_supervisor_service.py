from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import utcnow
from .program_models import CalyxProgram, CalyxProgramJob
from .sandbox_supervisor_evidence import (
    SupervisorValidationReceipt,
    ValidationRequestEnvelope,
)
from .sandbox_supervisor_models import SandboxValidationRequestRecord

MIN_CLAIM_SECONDS = 60
MAX_CLAIM_SECONDS = 600


def _as_utc(value: datetime) -> datetime:
    """Normalize database timestamps for Python-side comparisons.

    PostgreSQL preserves timezone-aware TIMESTAMPTZ values, while SQLite used by
    focused tests can round-trip DateTime(timezone=True) as a naive datetime.
    Treat a naive persisted value as UTC rather than allowing backend-specific
    datetime semantics to bypass or crash the lease boundary.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        self._validate_program_job_binding(
            owner=owner,
            program_job_id=program_job_id,
            repository=envelope.repository,
            branch=envelope.branch,
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
            targets_json=json.dumps(
                [item.as_dict() for item in envelope.targets], sort_keys=True
            ),
            timeout_seconds=envelope.timeout_seconds,
            request_digest=envelope.request_digest,
            status="queued",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> SandboxValidationRequestRecord | None:
        worker = worker_id.strip()
        if not worker:
            raise ValueError("SANDBOX_SUPERVISOR_WORKER_REQUIRED")
        if not MIN_CLAIM_SECONDS <= lease_seconds <= MAX_CLAIM_SECONDS:
            raise ValueError("SANDBOX_SUPERVISOR_LEASE_INVALID")
        self._recover_expired_claims()
        record = self.db.scalar(
            select(SandboxValidationRequestRecord)
            .where(SandboxValidationRequestRecord.status == "queued")
            .order_by(SandboxValidationRequestRecord.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        if record is None:
            self.db.commit()
            return None
        if record.attempt_count >= record.max_attempts:
            record.status = "blocked"
            record.outcome = "blocked"
            self.db.commit()
            return self.claim_next(worker_id=worker, lease_seconds=lease_seconds)
        now = utcnow()
        record.status = "claimed"
        record.claim_worker = worker
        record.claim_token = str(uuid4())
        record.claimed_at = now
        record.claim_expires_at = now + timedelta(seconds=lease_seconds)
        record.attempt_count += 1
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
        if (
            record.claim_expires_at is None
            or _as_utc(record.claim_expires_at) <= utcnow()
        ):
            raise PermissionError("SANDBOX_VALIDATION_CLAIM_EXPIRED")
        envelope = self._envelope(record)
        receipt = SupervisorValidationReceipt.from_mapping(receipt_payload)
        receipt.verify_for(envelope)
        record.authorization_id = receipt.authorization_id
        record.policy_digest = receipt.policy_digest
        record.evidence_uri = receipt.evidence_uri
        record.outcome = receipt.outcome
        record.receipt_digest = receipt.receipt_digest
        record.result_json = json.dumps(
            receipt.payload(), sort_keys=True, separators=(",", ":")
        )
        record.status = "completed" if receipt.outcome == "delivered" else "blocked"
        record.completed_at = utcnow()
        record.claim_token = None
        record.claim_expires_at = None
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_owned(
        self, *, owner: str, request_id: str
    ) -> SandboxValidationRequestRecord:
        record = self.db.get(SandboxValidationRequestRecord, request_id)
        if record is None or record.owner != owner:
            raise LookupError("SANDBOX_VALIDATION_REQUEST_NOT_FOUND")
        return record

    def get_completed_by_digest(
        self, *, request_digest: str
    ) -> SandboxValidationRequestRecord:
        """Resolve one persisted completed supervisor record by exact request digest."""
        digest = request_digest.strip().lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("SANDBOX_VALIDATION_REQUEST_DIGEST_INVALID")
        record = self.db.scalar(
            select(SandboxValidationRequestRecord).where(
                SandboxValidationRequestRecord.request_digest == digest,
                SandboxValidationRequestRecord.status == "completed",
            )
        )
        if record is None:
            raise LookupError("SANDBOX_VALIDATION_COMPLETED_RECORD_NOT_FOUND")
        if (
            record.outcome != "delivered"
            or not record.receipt_digest
            or not record.policy_digest
            or not record.authorization_id
            or not record.evidence_uri
        ):
            raise PermissionError("SANDBOX_VALIDATION_COMPLETED_RECORD_INVALID")
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
            "attempt_count": record.attempt_count,
            "max_attempts": record.max_attempts,
            "claim_expires_at": (
                record.claim_expires_at.isoformat() if record.claim_expires_at else None
            ),
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
            "claim_expires_at": (
                record.claim_expires_at.isoformat() if record.claim_expires_at else None
            ),
            "attempt_count": record.attempt_count,
            "max_attempts": record.max_attempts,
        }

    def _validate_program_job_binding(
        self,
        *,
        owner: str,
        program_job_id: str | None,
        repository: str,
        branch: str,
    ) -> None:
        if program_job_id is None:
            return
        job = self.db.get(CalyxProgramJob, program_job_id)
        if job is None:
            raise LookupError("SANDBOX_VALIDATION_PROGRAM_JOB_NOT_FOUND")
        program = self.db.get(CalyxProgram, job.program_id)
        if program is None or program.owner != owner:
            raise LookupError("SANDBOX_VALIDATION_PROGRAM_JOB_NOT_FOUND")
        if job.mutating:
            raise PermissionError("SANDBOX_VALIDATION_MUTATING_JOB_PROHIBITED")
        if job.repository != repository or (job.branch or "") != branch:
            raise PermissionError("SANDBOX_VALIDATION_PROGRAM_JOB_IDENTITY_MISMATCH")

    def _recover_expired_claims(self) -> None:
        now = utcnow()
        expired = self.db.scalars(
            select(SandboxValidationRequestRecord).where(
                SandboxValidationRequestRecord.status == "claimed",
                SandboxValidationRequestRecord.claim_expires_at.is_not(None),
                SandboxValidationRequestRecord.claim_expires_at <= now,
            )
        ).all()
        for record in expired:
            record.claim_worker = None
            record.claim_token = None
            record.claimed_at = None
            record.claim_expires_at = None
            if record.attempt_count >= record.max_attempts:
                record.status = "blocked"
                record.outcome = "blocked"
            else:
                record.status = "queued"

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
