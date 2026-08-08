from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.sandbox_supervisor_evidence import (
    SupervisorCredentialVerifier,
    SupervisorValidationReceipt,
    ValidationRequestEnvelope,
)
from app.calyx_orchestrator.sandbox_supervisor_models import SandboxValidationRequestRecord
from app.calyx_orchestrator.sandbox_supervisor_service import SandboxSupervisorService
from app.database import Base

TOKEN = "supervisor-token-with-at-least-thirty-two-bytes"
TOKEN_SHA = hashlib.sha256(TOKEN.encode()).hexdigest()
TARGET_SHA = "a" * 64
POLICY_SHA = "b" * 64
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[SandboxValidationRequestRecord.__table__])
    return Session(engine)


def _envelope() -> ValidationRequestEnvelope:
    return ValidationRequestEnvelope.build(
        repository="jsp1440/orchid-calyx-backend",
        branch="autonomy/example",
        checkout_commit_sha="c" * 40,
        preset="pytest",
        targets=[{"path": "tests/test_example.py", "sha256": TARGET_SHA}],
        timeout_seconds=60,
    )


def _receipt(request_digest: str) -> dict:
    return {
        "request_digest": request_digest,
        "authorization_id": "sandbox-auth-1",
        "policy_digest": POLICY_SHA,
        "evidence_uri": "github-actions:run/123",
        "outcome": "delivered",
        "return_code": 0,
        "stdout_sha256": EMPTY_SHA,
        "stderr_sha256": EMPTY_SHA,
        "issued_at": datetime(2026, 8, 8, 20, 0, tzinfo=timezone.utc).isoformat(),
    }


def test_supervisor_credential_is_one_way_and_fail_closed() -> None:
    verifier = SupervisorCredentialVerifier.from_environ(
        {"CALYX_SANDBOX_SUPERVISOR_TOKEN_SHA256": TOKEN_SHA}
    )
    verifier.verify(TOKEN)
    with pytest.raises(PermissionError, match="CREDENTIAL_REJECTED"):
        verifier.verify("wrong-token-that-is-long-enough-to-be-rejected")
    with pytest.raises(RuntimeError, match="NOT_CONFIGURED"):
        SupervisorCredentialVerifier.from_environ({})


def test_request_digest_binds_revision_command_targets_and_timeout() -> None:
    envelope = _envelope()
    changed = ValidationRequestEnvelope.build(
        repository=envelope.repository,
        branch=envelope.branch,
        checkout_commit_sha="d" * 40,
        preset=envelope.preset,
        targets=[item.as_dict() for item in envelope.targets],
        timeout_seconds=envelope.timeout_seconds,
    )
    assert envelope.request_digest != changed.request_digest
    with pytest.raises(PermissionError, match="PYTEST_TARGET_NOT_TEST"):
        ValidationRequestEnvelope.build(
            repository=envelope.repository,
            branch=envelope.branch,
            checkout_commit_sha=envelope.checkout_commit_sha,
            preset="pytest",
            targets=[{"path": "app/example.py", "sha256": TARGET_SHA}],
            timeout_seconds=60,
        )


def test_receipt_must_match_exact_request_digest() -> None:
    envelope = _envelope()
    receipt = SupervisorValidationReceipt.from_mapping(_receipt(envelope.request_digest))
    receipt.verify_for(envelope)
    bad = SupervisorValidationReceipt.from_mapping(_receipt("0" * 64))
    with pytest.raises(PermissionError, match="REQUEST_MISMATCH"):
        bad.verify_for(envelope)


def test_durable_claim_completion_never_exposes_claim_token_to_owner() -> None:
    envelope = _envelope()
    with _db() as db:
        service = SandboxSupervisorService(db)
        created = service.create_request(
            owner="owner-1",
            program_job_id="job-1",
            repository=envelope.repository,
            branch=envelope.branch,
            checkout_commit_sha=envelope.checkout_commit_sha,
            preset=envelope.preset,
            targets=[item.as_dict() for item in envelope.targets],
            timeout_seconds=envelope.timeout_seconds,
        )
        duplicate = service.create_request(
            owner="owner-1",
            program_job_id="job-1",
            repository=envelope.repository,
            branch=envelope.branch,
            checkout_commit_sha=envelope.checkout_commit_sha,
            preset=envelope.preset,
            targets=[item.as_dict() for item in envelope.targets],
            timeout_seconds=envelope.timeout_seconds,
        )
        assert duplicate.request_id == created.request_id
        claimed = service.claim_next(worker_id="external-supervisor-1")
        assert claimed is not None and claimed.claim_token
        owner_view = service.public_snapshot(claimed)
        assert "claim_token" not in owner_view
        assert owner_view["claim_token_exposed"] is False
        completed = service.complete(
            request_id=claimed.request_id,
            worker_id="external-supervisor-1",
            claim_token=claimed.claim_token,
            receipt_payload=_receipt(claimed.request_digest),
        )
        assert completed.status == "completed"
        assert completed.outcome == "delivered"
        assert completed.claim_token is None
        assert completed.receipt_digest


def test_stale_claim_or_receipt_fails_closed() -> None:
    envelope = _envelope()
    with _db() as db:
        service = SandboxSupervisorService(db)
        created = service.create_request(
            owner="owner-1",
            program_job_id=None,
            repository=envelope.repository,
            branch=envelope.branch,
            checkout_commit_sha=envelope.checkout_commit_sha,
            preset=envelope.preset,
            targets=[item.as_dict() for item in envelope.targets],
            timeout_seconds=envelope.timeout_seconds,
        )
        claimed = service.claim_next(worker_id="external-supervisor-1")
        assert claimed is not None and claimed.claim_token
        with pytest.raises(PermissionError, match="CLAIM_MISMATCH"):
            service.complete(
                request_id=created.request_id,
                worker_id="external-supervisor-2",
                claim_token=claimed.claim_token,
                receipt_payload=_receipt(created.request_digest),
            )
        with pytest.raises(PermissionError, match="REQUEST_MISMATCH"):
            service.complete(
                request_id=created.request_id,
                worker_id="external-supervisor-1",
                claim_token=claimed.claim_token,
                receipt_payload=_receipt("0" * 64),
            )
