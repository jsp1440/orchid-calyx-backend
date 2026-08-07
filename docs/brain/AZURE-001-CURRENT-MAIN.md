# AZURE-001 — Current-main taxonomy preflight and attestation guardrails

Date: 2026-08-07
PR: #572
Base main: `7be9c5f7831672129047956c09d47d95ae6442a4`
Implementation head: `e1bdf7c25d95c72bf15e5f12a3838fe4962fa983`
Source lane superseded after release: #459

## Objective

Rebuild the unique, non-production Azure/taxonomy guardrail framework from stale PR #459 directly on authoritative current main without importing stale Calyx application code or asserting any external readiness gate.

## Current-main rebuild

The release branch ports 32 additive artifacts:

- deterministic taxonomy preflight validation;
- governed execution wrapper and bounded policy/schema contracts;
- release-gate planning, execution, verification, and locking;
- byte-for-byte reproducibility checks;
- review-only readiness and acceptance packet generation;
- typed external-gate attestation validation;
- canonical attestation-register management;
- Azure landing-zone, service-inventory, cost-guardrail, release-checklist, and operator-runbook documentation;
- two focused GitHub Actions validation workflows;
- eight focused test modules.

No existing Calyx application code, database migration, deployment configuration, production database, or Knowledge Graph path is modified by the rebuilt subsystem.

## Exact-head executable validation

Implementation head `e1bdf7c25d95c72bf15e5f12a3838fe4962fa983` passed all four triggered release lanes:

- Taxonomy Preflight CI run `31224661143` — success. Compile, focused unit tests, governed release-gate smoke validation, evidence upload, fail-closed readiness/acceptance behavior, and non-authority assertions all passed.
- Taxonomy Attestation Register CI run `31224661211` — success. Compile, register tests, canonical CI-attestation exercise, and evidence upload passed.
- CALYX Workflow Governance Audit run `31224661191` — success.
- BUILD-088E Validation run `31224661151` — success. PostgreSQL publication pipeline/readiness, BUILD-088B through BUILD-088D isolated regressions, compile, and lint all passed.

## Fail-closed authority state

The subsystem remains non-authoritative by design. Validation may generate evidence and readiness decisions, but it does not grant authority to perform any of the following:

- Azure provisioning;
- taxonomy activation or publication;
- scientific publication;
- production database mutation;
- production Knowledge Graph mutation;
- Render/Neon migration or shutdown;
- credential creation or disclosure;
- production deployment.

Synthetic CI intentionally produces `HOLD` / `REVIEW_ONLY` when required external attestations are absent.

## External gates still unresolved

The following are not asserted by this release and must remain false/unverified until durable evidence exists:

1. Exact August 2026 WorldOrchids / World Plants source-file checksum and real-dataset preflight evidence.
2. Microsoft nonprofit-credit / Azure billing-subscription linkage evidence.
3. Azure budget-alert configuration evidence.
4. Microsoft or partner architecture-review evidence.
5. Separate explicit go/no-go before any Azure resource creation.

## Release conclusion

AZURE-001 on PR #572 is a validated current-main guardrail and evidence framework. It is safe to release as infrastructure for later acceptance work because every production-authority flag remains false. Merging this framework does not constitute Azure activation, taxonomy promotion, publication approval, or production migration.
