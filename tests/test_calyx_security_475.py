from __future__ import annotations

from pathlib import Path

from app.security_audit import (
    OWNER_READINESS_POLICY,
    SecurityEventLedger,
    audit_router_sources,
    audit_workflow_permissions,
)
from app.security_governance import REDACTED, SECRET_REFERENCES, SecurityGovernanceInspector, redact_sensitive


def test_secret_inventory_exposes_names_not_values(monkeypatch):
    for name in SECRET_REFERENCES:
        monkeypatch.setenv(name, f"sensitive-{name}")
    payload = SecurityGovernanceInspector().public_payload()
    assert payload["contains_secret_values"] is False
    assert payload["secret_values_exposed"] is False
    assert set(payload["configured_secret_references"]) == set(SECRET_REFERENCES)
    serialized = repr(payload)
    assert "sensitive-" not in serialized


def test_missing_security_configuration_produces_exact_findings(monkeypatch):
    for name in SECRET_REFERENCES:
        monkeypatch.delenv(name, raising=False)
    readiness = SecurityGovernanceInspector().inspect()
    codes = {finding.code for finding in readiness.findings}
    assert "SECURITY_REFERENCES_MISSING" in codes
    assert "OWNER_SESSION_SIGNING_NOT_CONFIGURED" in codes
    assert "BACKEND_API_KEY_NOT_CONFIGURED" in codes


def test_governance_boundaries_are_permanently_false(monkeypatch):
    for name in SECRET_REFERENCES:
        monkeypatch.setenv(name, "configured")
    readiness = SecurityGovernanceInspector().inspect()
    assert readiness.credential_rotation_authorized is False
    assert readiness.penetration_attack_authorized is False
    assert readiness.deployment_authorized is False
    assert readiness.merge_authorized is False


def test_readiness_digest_is_stable_for_same_configuration(monkeypatch):
    for name in SECRET_REFERENCES:
        monkeypatch.setenv(name, "configured")
    inspector = SecurityGovernanceInspector()
    first = inspector.inspect()
    second = inspector.inspect()
    assert first.digest == second.digest
    assert first.generated_at <= second.generated_at


def test_sensitive_log_redaction():
    text = "api_key=abc token:xyz password=hunter2 database_url=postgres://private harmless=visible"
    redacted = redact_sensitive(text)
    assert redacted.count(REDACTED) == 4
    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "hunter2" not in redacted
    assert "postgres://private" not in redacted
    assert "harmless=visible" in redacted


def test_sensitive_header_redaction_consumes_full_header_value():
    text = (
        "Authorization: Bearer super-secret-token\n"
        "Cookie: session=private-cookie; Path=/\n"
        "harmless=visible"
    )
    redacted = redact_sensitive(text)
    assert redacted.count(REDACTED) == 2
    assert "super-secret-token" not in redacted
    assert "private-cookie" not in redacted
    assert "Bearer" not in redacted
    assert "harmless=visible" in redacted


def test_least_privilege_policy_denies_governed_actions():
    assert OWNER_READINESS_POLICY.permits("read_security_readiness") is True
    assert OWNER_READINESS_POLICY.permits("read_security_events") is True
    assert OWNER_READINESS_POLICY.permits("rotate_credentials") is False
    assert OWNER_READINESS_POLICY.permits("deploy") is False
    assert OWNER_READINESS_POLICY.permits("merge") is False


def test_route_audit_flags_mutating_route_without_auth_marker(tmp_path: Path):
    routers = tmp_path / "routers"
    routers.mkdir()
    (routers / "unsafe.py").write_text(
        "from fastapi import APIRouter\nrouter=APIRouter()\n@router.post('/unsafe')\ndef unsafe(): return {}\n",
        encoding="utf-8",
    )
    (routers / "safe.py").write_text(
        "from app.security import verify_owner_or_api_key\n@router.post('/safe')\ndef safe(): return {}\n",
        encoding="utf-8",
    )
    audit = audit_router_sources(routers)
    assert audit["audited_routes"] == 2
    assert [item["route"] for item in audit["findings"]] == ["/unsafe"]


def test_workflow_permissions_audit_flags_implicit_and_write_all(tmp_path: Path):
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "implicit.yml").write_text("name: implicit\njobs: {}\n", encoding="utf-8")
    (workflows / "broad.yml").write_text("name: broad\npermissions: write-all\njobs: {}\n", encoding="utf-8")
    audit = audit_workflow_permissions(workflows)
    codes = {item["code"] for item in audit["findings"]}
    assert "WORKFLOW_PERMISSIONS_IMPLICIT" in codes
    assert "WORKFLOW_WRITE_ALL" in codes


def test_security_event_ledger_redacts_and_is_immutable(tmp_path: Path):
    ledger = SecurityEventLedger(tmp_path / "events")
    event = ledger.append(
        actor="owner-a",
        event_type="security_fixture",
        detail="Authorization: Bearer do-not-store-this",
        severity="high",
    )
    assert event["immutable"] is True
    assert "do-not-store-this" not in repr(event)
    assert REDACTED in event["detail"]
    listed = ledger.list_events()
    assert listed == [event]
