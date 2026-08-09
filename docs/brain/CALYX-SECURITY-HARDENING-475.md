# CALYX-475 — Security, secret governance, authorization, and audit hardening

Status: IMPLEMENTED / EXECUTABLE VALIDATION BLOCKED BY HOSTED RUNNER

## Delivered

This slice adds a bounded security-governance inspector that inventories secret references by environment-variable name only, never their values; produces deterministic readiness findings with exact remediation; provides reusable sensitive-log redaction; and encodes permanent prohibitions on credential rotation, penetration attacks, deployment, and merge.

It now also includes:

- a bounded authorization-route source audit that identifies mutating route decorators lacking any established Calyx authentication marker and returns exact remediation;
- a GitHub Actions permission audit that flags workflows with implicit permissions or `write-all`;
- an explicit least-privilege policy for security readiness/events that denies credential rotation, penetration attacks, deployment, and merge;
- an append-only immutable security-event ledger whose details are redacted before persistence;
- protected Mission Control `/brain/mission-control/security/readiness` and `/events` APIs using the existing owner/API-key dependency;
- owner-scope enforcement and bounded event pagination.

## Findings model

The readiness surface distinguishes missing deployment configuration from code defects. Missing secret references produce `SECURITY_REFERENCES_MISSING`; absent owner-session signing produces `OWNER_SESSION_SIGNING_NOT_CONFIGURED`; absent backend API-key configuration produces `BACKEND_API_KEY_NOT_CONFIGURED`. Route/workflow audits add concrete file/method/route or workflow-path findings without exposing credential values.

## Review hardening

Static review found and corrected multiple defects before release:

1. The readiness digest originally included `generated_at`, making otherwise identical security state produce a different digest on every inspection. The digest now excludes observation time and is deterministic for identical configuration/findings.
2. Generic key/value redaction could turn `Authorization: Bearer <token>` into `Authorization=[REDACTED] <token>`, leaving the real bearer token visible. Authorization and Cookie headers now redact the entire header value before generic token/key/password/database-url redaction runs.
3. The original focused workflow secret guard used brittle mixed quoting. It now uses a simpler bounded pattern that does not embed shell-quote escapes.
4. The initial slice lacked the issue-required protected readiness API, route-authorization audit, workflow-permission audit, least-privilege policy object, and immutable security-event record. Those are now implemented and covered by deterministic tests.

## Governance

CALYX-475 does not rotate credentials, perform penetration attacks, expose secrets, deploy, merge, or mutate production data. Existing security dependencies remain the authorization authority. Static audits are advisory and cannot grant permission.

## Validation

Deterministic tests cover secret-value non-exposure, exact missing-reference findings, permanent authority denials, stable readiness digests, full bearer/cookie redaction, least privilege, mutating-route auth findings, workflow-permission findings, and immutable redacted security events.

GitHub-hosted runner validation has repeatedly failed before the first executable step (`steps=null`) on this PR and unrelated repository workflows. Those zero-step failures are infrastructure failures and do not count as executable validation. The PR remains draft/unmerged until executable exact-head validation is available.
