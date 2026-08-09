from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.security_governance import SecurityFinding, SecurityGovernanceInspector, redact_sensitive

ROUTE_DECORATOR = re.compile(r"@(?:router|app)\.(post|put|patch|delete|get)\(\s*[\"']([^\"']+)")
MUTATING_METHODS = {"post", "put", "patch", "delete"}
AUTH_MARKERS = (
    "verify_owner_or_api_key",
    "verify_api_key",
    "verify_owner_session",
    "require_admin",
    "require_judge",
)


@dataclass(frozen=True, slots=True)
class LeastPrivilegePolicy:
    policy_id: str
    allowed_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    owner_scope_required: bool = True
    project_scope_required: bool = False

    def permits(self, action: str) -> bool:
        normalized = str(action or "").strip()
        return normalized in self.allowed_actions and normalized not in self.prohibited_actions


OWNER_READINESS_POLICY = LeastPrivilegePolicy(
    policy_id="owner-readiness-v1",
    allowed_actions=("read_security_readiness", "read_security_events"),
    prohibited_actions=("rotate_credentials", "penetration_attack", "deploy", "merge"),
)


class SecurityEventLedger:
    """Append-only local ledger; event content is redacted before persistence."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.environ.get("CALYX_SECURITY_EVENT_WORKSPACE", "/tmp/calyx/security-events"))

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, *, actor: str, event_type: str, detail: str, severity: str = "info") -> dict[str, Any]:
        if not actor.strip() or not event_type.strip():
            raise ValueError("SECURITY_EVENT_FIELDS_REQUIRED")
        base = {
            "schema_version": "calyx-security-event/v1",
            "actor": actor.strip(),
            "event_type": event_type.strip(),
            "severity": severity.strip() or "info",
            "detail": redact_sensitive(detail),
            "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        event_id = self._digest(base)
        record = {**base, "event_id": event_id, "immutable": True}
        path = self.root / f"{event_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError("SECURITY_EVENT_IMMUTABLE_CONFLICT")
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return record

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("SECURITY_EVENT_LIMIT_INVALID")
        if not self.root.exists():
            return []
        paths = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
        return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def audit_router_sources(root: Path | None = None) -> dict[str, Any]:
    base = root or Path("app/routers")
    findings: list[dict[str, Any]] = []
    audited_routes = 0
    if not base.exists():
        return {"audited_routes": 0, "findings": [{"code": "ROUTER_SOURCE_UNAVAILABLE", "severity": "info"}]}
    for path in sorted(base.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        has_auth_marker = any(marker in source for marker in AUTH_MARKERS)
        for method, route in ROUTE_DECORATOR.findall(source):
            audited_routes += 1
            if method in MUTATING_METHODS and not has_auth_marker:
                findings.append({
                    "code": "MUTATING_ROUTE_AUTH_REVIEW_REQUIRED",
                    "severity": "high",
                    "path": str(path),
                    "method": method.upper(),
                    "route": route,
                    "remediation": "Bind an existing owner/API-key/admin/judge authorization dependency or document why the route is intentionally public.",
                })
    return {"audited_routes": audited_routes, "findings": findings}


def audit_workflow_permissions(root: Path | None = None) -> dict[str, Any]:
    base = root or Path(".github/workflows")
    findings: list[dict[str, Any]] = []
    workflows = 0
    if not base.exists():
        return {"workflow_count": 0, "findings": [{"code": "WORKFLOW_SOURCE_UNAVAILABLE", "severity": "info"}]}
    for path in sorted(base.glob("*.y*ml")):
        workflows += 1
        source = path.read_text(encoding="utf-8")
        if "permissions:" not in source:
            findings.append({
                "code": "WORKFLOW_PERMISSIONS_IMPLICIT",
                "severity": "medium",
                "path": str(path),
                "remediation": "Declare explicit minimum GitHub Actions permissions at workflow or job scope.",
            })
        if re.search(r"permissions:\s*write-all", source):
            findings.append({
                "code": "WORKFLOW_WRITE_ALL",
                "severity": "critical",
                "path": str(path),
                "remediation": "Replace write-all with the minimum named permissions required by the workflow.",
            })
    return {"workflow_count": workflows, "findings": findings}


class SecurityReadinessService:
    def __init__(self, ledger: SecurityEventLedger | None = None) -> None:
        self.ledger = ledger or SecurityEventLedger()

    def readiness(self) -> dict[str, Any]:
        secret_state = SecurityGovernanceInspector().public_payload()
        routes = audit_router_sources()
        workflows = audit_workflow_permissions()
        findings = list(secret_state.get("findings") or []) + routes["findings"] + workflows["findings"]
        return {
            "schema_version": "calyx-security-readiness/v1",
            "secret_governance": secret_state,
            "route_audit": routes,
            "workflow_permission_audit": workflows,
            "least_privilege_policy": asdict(OWNER_READINESS_POLICY),
            "finding_count": len(findings),
            "findings": findings,
            "secret_values_exposed": False,
            "credential_rotation_authorized": False,
            "penetration_attack_authorized": False,
            "deployment_authorized": False,
            "merge_authorized": False,
        }
