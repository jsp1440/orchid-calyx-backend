from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class SandboxAuthorization:
    """Non-secret evidence that a trusted supervisor authorized one sandbox run."""

    authorization_id: str
    evidence_uri: str
    policy_digest: str
    request_digest: str

    def verify(self, *, expected_request_digest: str | None = None) -> None:
        if not self.authorization_id.strip():
            raise ValueError("SANDBOX_AUTHORIZATION_ID_REQUIRED")
        if ":" not in self.evidence_uri:
            raise ValueError("SANDBOX_AUTHORIZATION_EVIDENCE_URI_INVALID")
        policy_digest = self.policy_digest.strip().lower()
        if not _is_sha256(policy_digest):
            raise ValueError("SANDBOX_AUTHORIZATION_POLICY_DIGEST_INVALID")
        request_digest = self.request_digest.strip().lower()
        if not _is_sha256(request_digest):
            raise ValueError("SANDBOX_AUTHORIZATION_REQUEST_DIGEST_INVALID")
        if expected_request_digest is not None:
            expected = expected_request_digest.strip().lower()
            if not _is_sha256(expected):
                raise ValueError("SANDBOX_AUTHORIZATION_EXPECTED_REQUEST_DIGEST_INVALID")
            if request_digest != expected:
                raise PermissionError("SANDBOX_AUTHORIZATION_REQUEST_DIGEST_MISMATCH")


class SandboxValidationAuthorizer(Protocol):
    """Trusted-runtime boundary used to authorize executable repository validation.

    Implementations live outside the repository workspace and must verify that the
    sandbox controls represented by the marker are actually enforced for the exact
    workspace/repository/branch and request digest before returning authorization
    evidence.
    """

    def authorize(
        self,
        *,
        workspace_root: Path,
        repository: str,
        branch: str,
        marker: Mapping[str, object],
        request_digest: str,
    ) -> SandboxAuthorization: ...
