# CALYX CORE — Production migration 107 receipt

Date: 2026-08-08
Issue: #386
Parent: #384
Merged implementation: PR #619
Main merge SHA: `1ff4e38c49074d79f8ac26a8f9ae372c8d19fc71`

## Owner authorization

The owner explicitly authorized the production migration in conversation with: `yes go on migration`.

This authorization covered applying additive migration `107_world_plants_release_staging.sql` to the protected production database. It did not authorize taxonomy release activation, canonical species replacement, Knowledge Graph mutation, scientific publication, or unbounded harvesting.

## Pre-production validation

The exact implementation head `fea46c6d4b5e42db7821c8aa83b070371e7ce9ba` passed all five applicable PR gates before merge:

- CALYX World Plants Durable Staging Validation #22 — success;
- CALYX-TAXONOMY-READINESS-API-001 #27 — success;
- WORLD-PLANTS-UPLOAD-001 #84 — success;
- CALYX Workflow Governance Audit #330 — success;
- BUILD-088E Validation #1180 — success.

The dedicated PostgreSQL gate rehearsed read-only preflight, guarded apply, post-apply verification, and a second idempotent apply on disposable PostgreSQL 16.

## Production activation mechanism

The authorized merge added a one-time activation marker and protected workflow using:

- GitHub `production` environment;
- protected `DATABASE_URL` secret;
- exact-current-main checkout verification;
- explicit `CALYX_TAXONOMY_MIGRATION_CONFIRM=APPLY_107` token;
- pre/post schema verification;
- evidence artifact upload;
- automatic receipt reporting to issue #386.

The workflow trigger is bound to the first addition of `.github/activation/taxonomy-107-approved.txt` on `main`; later edits elsewhere do not retrigger the migration.

## Production result

The production activation receipt reported:

- status: `passed`;
- main SHA: `1ff4e38c49074d79f8ac26a8f9ae372c8d19fc71`;
- migration SHA-256: `93c267b02fc53fc3426ceacbb689766fae583a0b3626622aebe3ce6854fdfa44`;
- activation complete: `true`;
- production database mutation attempted: `true`;
- production database mutation observed: `true`;
- blockers: `[]`;
- taxonomy activation authorized: `false`;
- Knowledge Graph mutation authorized: `false`;
- activation artifact hash: `593af3513dba41c6b907cbf464e96a2eb1d406d73e081a3347750843ac8ef834`.

Therefore migration 107 is now active in the protected production database and the isolated `taxonomy_pipeline` staging schema exists and passed post-apply verification.

## Remaining governance boundary

The next state-changing step is a bounded production staging smoke using the real Hassler release. That operation writes staging evidence but does not activate taxonomy. It remains a separate production-database-write governance boundary.

Taxonomy activation remains separately prohibited until the full real release has been staged, its change report and review queue have been reviewed, and explicit owner approval for activation is recorded.
