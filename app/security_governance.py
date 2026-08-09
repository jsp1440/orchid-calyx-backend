from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

SECRET_REFERENCES = (
    "CALYX_API_KEY",
    "CALYX_OWNER_ACCESS_CODE",
    "CALYX_OWNER_SESSION_SECRET",
    "ORCHID_JUDGE_ADMIN_KEY",
    "DATABASE_URL",
)
REDACTED = "[REDACTED]"
_HEADER_SECRET_PATTERN = re.compile(r"(?im)\b(authorization|cookie)\b\s*:\s*([^\r\n]+)")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|database_url)\b\s*[:=]\s*([^\s,;]+)"
)


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    code: str
    severity: str
    remediation: str


@dataclass(frozen=True, slots=True)
class SecurityReadiness:
    schema_version: str
    generated_at: str
    configured_secret_references: tuple[str, ...]
    missing_secret_references: tuple[str, ...]
    secret_values_exposed: bool
    credential_rotation_authorized: bool
    penetration_attack_authorized: bool
    deployment_authorized: bool
    merge_authorized: bool
    findings: tuple[SecurityFinding, ...]
    digest: str


def redact_sensitive(value: str) -> str:
    """Best-effort log redaction; never use this as an authorization boundary."""
    redacted = _HEADER_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}: {REDACTED}", value
    )
    return _SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED}", redacted
    )


class SecurityGovernanceInspector:
    schema_version = "calyx-security-governance/v1"

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def inspect(self) -> SecurityReadiness:
        configured = tuple(sorted(name for name in SECRET_REFERENCES if os.getenv(name)))
        missing = tuple(sorted(set(SECRET_REFERENCES) - set(configured)))
        findings: list[SecurityFinding] = []
        if missing:
            findings.append(SecurityFinding(
                "SECURITY_REFERENCES_MISSING",
                "high",
                "Configure required secret references in the deployment secret store; do not commit values.",
            ))
        if not os.getenv("CALYX_OWNER_SESSION_SECRET"):
            findings.append(SecurityFinding(
                "OWNER_SESSION_SIGNING_NOT_CONFIGURED",
                "critical",
                "Configure CALYX_OWNER_SESSION_SECRET before enabling owner-session authentication.",
            ))
        if not os.getenv("CALYX_API_KEY"):
            findings.append(SecurityFinding(
                "BACKEND_API_KEY_NOT_CONFIGURED",
                "high",
                "Configure CALYX_API_KEY before relying on API-key protected routes.",
            ))
        base: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "configured_secret_references": configured,
            "missing_secret_references": missing,
            "secret_values_exposed": False,
            "credential_rotation_authorized": False,
            "penetration_attack_authorized": False,
            "deployment_authorized": False,
            "merge_authorized": False,
            "findings": tuple(findings),
        }
        digest_payload = {
            key: value
            for key, value in base.items()
            if key != "generated_at" and key != "findings"
        }
        digest_payload["findings"] = [asdict(item) for item in findings]
        return SecurityReadiness(**base, digest=self._digest(digest_payload))

    def public_payload(self) -> dict[str, Any]:
        result = asdict(self.inspect())
        result["contains_secret_values"] = False
        return result
