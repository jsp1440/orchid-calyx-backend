# CALYX CORE — Hassler durable intake and bounded-smoke preparation

Date: 2026-08-08
Issue: #386
PR: #647

## Context

Migration 107 was authorized by the owner and activated successfully in production before this build. Production evidence recorded on issue #386 showed:

- production main SHA: `1ff4e38c49074d79f8ac26a8f9ae372c8d19fc71`;
- migration status: `passed`;
- migration SHA-256: `93c267b02fc53fc3426ceacbb689766fae583a0b3626622aebe3ce6854fdfa44`;
- schema activation complete: true;
- production mutation observed: true;
- taxonomy activation authorized: false;
- Knowledge Graph mutation authorized: false;
- blockers: none.

The immutable production receipt was subsequently merged into the Brain through PR #643.

## Read-only deployed discovery

A GitHub-hosted read-only probe was added and run against the deployed Render backend. The successful discovery evidence established:

- migration preflight HTTP 200;
- taxonomy readiness HTTP 200;
- release-list HTTP 200;
- migration state `migration_verified`;
- migration schema complete `true`;
- production taxonomy intake release count `0`;
- exact Hassler release present `false`;
- no upload invoked;
- no staging invoked;
- no production mutation;
- taxonomy activation unauthorized;
- Knowledge Graph mutation unauthorized.

The exact expected real release remains:

`WorldOrchids 26-08 (Aug 2 2026).csv`

SHA-256:

`e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`

The live discovery also exposed three readiness blockers:

1. local `/var/data/taxonomy-intake` volume absent;
2. stale `CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED` operator flag false even though live migration preflight verifies the schema;
3. smoke-fixture verification not yet recorded.

## Architecture correction

The first two blockers were implementation/configuration artifacts, not legitimate scientific or governance dependencies.

Migration 107 already provides an immutable PostgreSQL source-byte store in `taxonomy_pipeline.releases.source_payload`. Requiring a Render filesystem volume in addition to that database duplicated durability mechanisms and prevented intake even though the authoritative staging database was healthy.

This build therefore adds `PostgresWorldPlantsIntakeStore` and makes PostgreSQL the preferred authoritative intake store whenever migration 107 is available. The legacy filesystem `WorldPlantsReleaseStore` remains a compatibility fallback for development and dependency-light environments.

The durable adapter preserves:

- the existing inspect/get/list API contract;
- exact source bytes and SHA-256 identity;
- source filename, version and acquisition provenance;
- the existing upload-size ceiling;
- bounded staging and checkpoint semantics;
- automatic promotion disabled;
- taxonomy activation blocked;
- Knowledge Graph mutation blocked.

Mission Control readiness now accepts live migration-preflight evidence as authoritative for the staging-schema and persistent-intake gates. It no longer requires a local volume when PostgreSQL durable source storage is verified. Environment flags remain a fallback for lightweight test/development contexts.

The smoke-fixture gate is deliberately not bypassed. It remains the next production-write boundary.

## Validation

Implementation head `0a53335ddb17959daf33ea87be0dcbdf33bdcf90` passed all applicable gates before this Brain receipt:

- CALYX World Plants Durable Staging Validation #29 — success;
- CALYX-TAXONOMY-READINESS-API-001 #35 — success;
- WORLD-PLANTS-UPLOAD-001 #91 — success;
- CALYX Hassler Intake Discovery #12 — success;
- CALYX Workflow Governance Audit #403 — success;
- BUILD-088E Validation #1199 — success.

The PostgreSQL validation explicitly proves durable inspect/list/get and bounded staging work without a local intake directory, while existing upload/readiness regressions remain green.

## Governance boundary

This build performs no upload of the real Hassler release and no staging write to production. It does not activate taxonomy, alter canonical species, publish scientific knowledge, or mutate the Knowledge Graph.

The next state-changing action remains a governed production intake/smoke operation using the exact real Hassler source. That action requires separate owner authorization.
