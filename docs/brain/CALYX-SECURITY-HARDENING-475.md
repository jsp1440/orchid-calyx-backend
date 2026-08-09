# CALYX-475 — Security, secret governance, authorization, and audit hardening

Status: IMPLEMENTED / VALIDATION PENDING

## Delivered

This slice adds a bounded security-governance inspector that inventories secret references by environment-variable name only, never their values; produces deterministic readiness findings with exact remediation; provides reusable sensitive-log redaction; and encodes permanent prohibitions on credential rotation, penetration attacks, deployment, and merge.

## Findings model

The readiness surface distinguishes missing deployment configuration from code defects. Missing secret references produce `SECURITY_REFERENCES_MISSING`; absent owner-session signing produces `OWNER_SESSION_SIGNING_NOT_CONFIGURED`; absent backend API-key configuration produces `BACKEND_API_KEY_NOT_CONFIGURED`. No finding contains a credential value.

## Review hardening

Static review found and corrected two security defects before release:

1. The readiness digest originally included `generated_at`, making otherwise identical security state produce a different digest on every inspection. The digest now excludes observation time and is deterministic for identical configuration/findings.
2. Generic key/value redaction could turn `Authorization: Bearer <token>` into `Authorization=[REDACTED] <token>`, leaving the real bearer token visible. Authorization and Cookie headers now redact the entire header value before generic token/key/password/database-url redaction runs.

Focused regressions cover deterministic digest replay and full bearer/cookie header-value redaction.

## Governance

CALYX-475 does not rotate credentials, perform penetration attacks, expose secrets, deploy, merge, or mutate production data. Authentication enforcement remains with the existing security dependencies. The inspector is advisory/read-only and cannot grant authorization.

## Validation

Deterministic tests prove secret values do not enter the public payload, missing references yield exact findings, governance permissions remain false even when all references are configured, readiness digests are stable for identical state, and representative log/header secrets are redacted while non-sensitive fields remain visible.

Hosted GitHub Actions validation is required on the exact post-review head. Zero-step `steps=null` runs are infrastructure failures and do not count as executable validation.
