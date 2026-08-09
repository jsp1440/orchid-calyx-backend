from __future__ import annotations

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
