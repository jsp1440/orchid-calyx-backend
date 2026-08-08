from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SUPERVISOR_TOKEN_SHA256_ENV = "CALYX_SANDBOX_SUPERVISOR_TOKEN_SHA256"
ALLOWED_PRESETS = frozenset({"pytest", "ruff"})
MAX_TARGETS = 24
MAX_TIMEOUT_SECONDS = 120


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SupervisorCredentialVerifier:
    """Verify a supervisor bearer token without storing the bearer token itself."""

    expected_sha256: str

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> SupervisorCredentialVerifier:
        source = os.environ if environ is None else environ
        digest = str(source.get(SUPERVISOR_TOKEN_SHA256_ENV, "")).strip().lower()
        if not _is_sha256(digest):
            raise RuntimeError("SANDBOX_SUPERVISOR_CREDENTIAL_NOT_CONFIGURED")
        return cls(expected_sha256=digest)

    def verify(self, token: str) -> None:
        normalized = token.strip()
        if len(normalized) < 32:
            raise PermissionError("SANDBOX_SUPERVISOR_CREDENTIAL_REJECTED")
        actual = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual, self.expected_sha256):
            raise PermissionError("SANDBOX_SUPERVISOR_CREDENTIAL_REJECTED")


@dataclass(frozen=True, slots=True)
class ValidationTarget:
    path: str
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ValidationTarget:
        path = str(value.get("path") or "").strip()
        digest = str(value.get("sha256") or "").strip().lower()
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("SANDBOX_VALIDATION_TARGET_PATH_INVALID")
        if not path.startswith(("app/", "tests/")):
            raise PermissionError("SANDBOX_VALIDATION_TARGET_PATH_NOT_ALLOWED")
        if not _is_sha256(digest):
            raise ValueError("SANDBOX_VALIDATION_TARGET_HASH_INVALID")
        return cls(path=path, sha256=digest)

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ValidationRequestEnvelope:
    repository: str
    branch: str
    checkout_commit_sha: str
    preset: str
    targets: tuple[ValidationTarget, ...]
    timeout_seconds: int

    @classmethod
    def build(
        cls,
        *,
        repository: str,
        branch: str,
        checkout_commit_sha: str,
        preset: str,
        targets: list[Mapping[str, Any]],
        timeout_seconds: int,
    ) -> ValidationRequestEnvelope:
        normalized_repository = repository.strip()
        normalized_branch = branch.strip()
        normalized_commit = checkout_commit_sha.strip().lower()
        normalized_preset = preset.strip().lower()
        if not normalized_repository or "/" not in normalized_repository:
            raise ValueError("SANDBOX_VALIDATION_REPOSITORY_INVALID")
        if not normalized_branch.startswith("autonomy/"):
            raise PermissionError("SANDBOX_VALIDATION_AUTONOMY_BRANCH_REQUIRED")
        if len(normalized_commit) != 40 or any(
            c not in "0123456789abcdef" for c in normalized_commit
        ):
            raise ValueError("SANDBOX_VALIDATION_COMMIT_INVALID")
        if normalized_preset not in ALLOWED_PRESETS:
            raise ValueError("SANDBOX_VALIDATION_PRESET_NOT_ALLOWED")
        if not targets or len(targets) > MAX_TARGETS:
            raise ValueError("SANDBOX_VALIDATION_TARGET_COUNT_INVALID")
        parsed = tuple(ValidationTarget.from_mapping(item) for item in targets)
        if len({item.path for item in parsed}) != len(parsed):
            raise ValueError("SANDBOX_VALIDATION_DUPLICATE_TARGET")
        if normalized_preset == "pytest" and any(
            not item.path.startswith("tests/") for item in parsed
        ):
            raise PermissionError("SANDBOX_VALIDATION_PYTEST_TARGET_NOT_TEST")
        if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError("SANDBOX_VALIDATION_TIMEOUT_INVALID")
        return cls(
            repository=normalized_repository,
            branch=normalized_branch,
            checkout_commit_sha=normalized_commit,
            preset=normalized_preset,
            targets=parsed,
            timeout_seconds=timeout_seconds,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "calyx-external-validation-request-v1",
            "repository": self.repository,
            "branch": self.branch,
            "checkout_commit_sha": self.checkout_commit_sha,
            "preset": self.preset,
            "targets": [item.as_dict() for item in sorted(self.targets, key=lambda item: item.path)],
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def request_digest(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class SupervisorValidationReceipt:
    request_digest: str
    authorization_id: str
    policy_digest: str
    evidence_uri: str
    outcome: str
    return_code: int | None
    stdout_sha256: str
    stderr_sha256: str
    issued_at: datetime

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SupervisorValidationReceipt:
        request_digest = str(value.get("request_digest") or "").strip().lower()
        policy_digest = str(value.get("policy_digest") or "").strip().lower()
        stdout_digest = str(value.get("stdout_sha256") or "").strip().lower()
        stderr_digest = str(value.get("stderr_sha256") or "").strip().lower()
        if not all(
            _is_sha256(item)
            for item in (request_digest, policy_digest, stdout_digest, stderr_digest)
        ):
            raise ValueError("SANDBOX_SUPERVISOR_RECEIPT_DIGEST_INVALID")
        authorization_id = str(value.get("authorization_id") or "").strip()
        evidence_uri = str(value.get("evidence_uri") or "").strip()
        if not authorization_id or ":" not in evidence_uri:
            raise ValueError("SANDBOX_SUPERVISOR_RECEIPT_IDENTITY_INVALID")
        outcome = str(value.get("outcome") or "").strip().lower()
        if outcome not in {"delivered", "blocked", "timed_out"}:
            raise ValueError("SANDBOX_SUPERVISOR_RECEIPT_OUTCOME_INVALID")
        raw_code = value.get("return_code")
        return_code = None if raw_code is None else int(raw_code)
        if outcome == "delivered" and return_code != 0:
            raise ValueError("SANDBOX_SUPERVISOR_RECEIPT_SUCCESS_CODE_INVALID")
        raw_issued_at = str(value.get("issued_at") or "").strip()
        try:
            issued_at = datetime.fromisoformat(raw_issued_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("SANDBOX_SUPERVISOR_RECEIPT_TIME_INVALID") from exc
        if issued_at.tzinfo is None:
            raise ValueError("SANDBOX_SUPERVISOR_RECEIPT_TIME_INVALID")
        return cls(
            request_digest=request_digest,
            authorization_id=authorization_id,
            policy_digest=policy_digest,
            evidence_uri=evidence_uri,
            outcome=outcome,
            return_code=return_code,
            stdout_sha256=stdout_digest,
            stderr_sha256=stderr_digest,
            issued_at=issued_at.astimezone(timezone.utc),
        )

    def verify_for(self, request: ValidationRequestEnvelope) -> None:
        if not hmac.compare_digest(self.request_digest, request.request_digest):
            raise PermissionError("SANDBOX_SUPERVISOR_RECEIPT_REQUEST_MISMATCH")

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "calyx-external-validation-receipt-v1",
            "request_digest": self.request_digest,
            "authorization_id": self.authorization_id,
            "policy_digest": self.policy_digest,
            "evidence_uri": self.evidence_uri,
            "outcome": self.outcome,
            "return_code": self.return_code,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "issued_at": self.issued_at.isoformat(),
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256(self.payload())
