from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class SandboxAuthorization:
    """Non-secret evidence that a trusted supervisor authorized one sandbox run."""

    authorization_id: str
    evidence_uri: str
    policy_digest: str

    def verify(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("SANDBOX_AUTHORIZATION_ID_REQUIRED")
        if ":" not in self.evidence_uri:
            raise ValueError("SANDBOX_AUTHORIZATION_EVIDENCE_URI_INVALID")
        digest = self.policy_digest.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("SANDBOX_AUTHORIZATION_POLICY_DIGEST_INVALID")


class SandboxValidationAuthorizer(Protocol):
    """Trusted-runtime boundary used to authorize executable repository validation.

    Implementations live outside the repository workspace and must verify that the
    sandbox controls represented by the marker are actually enforced for this exact
    workspace/repository/branch before returning authorization evidence.
    """

    def authorize(
        self,
        *,
        workspace_root: Path,
        repository: str,
        branch: str,
        marker: Mapping[str, object],
    ) -> SandboxAuthorization: ...
