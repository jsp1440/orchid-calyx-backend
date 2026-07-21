# BUILD-088E — Publication Pipeline Operational Readiness

## Scope

BUILD-088E validates the merged BUILD-088 publication architecture as one PostgreSQL-authoritative system, from immutable Evidence Packets through interpretation, canonical assertion, governed publication, atomic graph versioning, lifecycle management, historical reconstruction, rollback, projections, and reverse provenance. It adds only the missing integration and read-only operational validation infrastructure.

## Architecture compliance

The implementation reuses the BUILD-087 scientific layers, BUILD-088B policy and publication registries, BUILD-088C mapper and atomic graph writer, and BUILD-088D lifecycle repository. It adds no publication API, alternate graph store, repository replacement, destructive migration, graph rebuild, direct protected-schema writer, or public publication path. Existing records remain append-only.

Two integration records required for operational proof are now part of the existing atomic publication transaction:

- a successful initial publication appends its `AUTHORITATIVE_CURRENT` projection event;
- a replay of a committed transaction appends a `NO_OP_DUPLICATE` transaction attempt before returning the existing graph version.

## End-to-end pipeline

The PostgreSQL corpus automatically exercises:

1. Evidence Packet → interpretation → automatic routing → canonical assertion → publication candidate → authorization → atomic graph publication → current/historical projection → reverse provenance.
2. Duplicate and concurrent publication with one commit and deterministic no-op attempts.
3. Correction/supersession with a newer assertion version and preserved predecessor history.
4. Withdrawal followed by an explicitly governed restoration.
5. Retraction with dependent-publication reevaluation and downstream impact records.
6. Technical rollback of the latest graph version to its coherent parent without deleting the failed version, objects, transaction, or provenance.
7. Arbitrary historical graph reconstruction from immutable version/object records.

An unauthorized or incomplete publication continues to fail before graph mutation through the existing BUILD-088B/C gates. Existing BUILD-088C atomic rollback-on-error tests remain part of the regression matrix.

## Operational validators

`PostgresPublicationReadinessRepository` validates one repeatable-read, read-only database snapshot and returns immutable structured findings. Every finding contains component, reason, severity, count, and recommended action. Validation covers:

- publication and policy registry integrity;
- migration tables, append-only triggers, indexes, and constraints;
- graph version sequence, parent lineage, current pointer, transactions, and object identities;
- assertion-to-source provenance coverage and orphan detection;
- lifecycle transition history, supersession lineage, current/historical projections, and duplicate suppression;
- rollback manifests/transactions, audit completeness, reevaluation, and dependency propagation.

No validator repairs, deletes, rewrites, or silently downgrades a failed invariant.

## Readiness service

`validate()` returns counts, projection statistics, provenance coverage, duplicate-suppression counts, lookup observations, and all findings. `require_healthy()` fails closed with `PUBLICATION_SYSTEM_NOT_READY`; inability to connect or validate fails with `READINESS_VALIDATION_UNAVAILABLE`.

## Reporting and performance

The report includes publication, policy, graph version/object, active/withdrawn/retracted/superseded, rollback, reevaluation, projection, provenance, and duplicate counts. It records wall-clock observations for publication, duplicate, current graph-version, current projection, lineage, historical reconstruction, provenance, and rollback lookups. Queries are bounded and use the merged lookup indexes; no full evidence content or secret value is copied into the report.

The deterministic validation corpus contains seven governed publications and exercises concurrent submissions with three workers. Performance observations are diagnostic, not service-level guarantees; deployment-specific baselines remain an operational responsibility.

## Exact validation

- Focused BUILD-088E plus BUILD-088C/D local validation: `10 passed, 3 skipped` (PostgreSQL tests skipped locally because `TEST_DATABASE_URL` is unavailable).
- Full local backend suite: `718 passed, 24 skipped, 1 failed`; the sole failure is the independently reproducible BUILD-085 Windows subprocess environment failure, with PostgreSQL tests skipped when the database URL was unavailable.
- Changed-scope Ruff, Python compilation, and `git diff --check`: passed.
- PostgreSQL 16 pipeline/readiness and isolated BUILD-088B–D regression: executed by `.github/workflows/build-088e-validation.yml`; exact pull-request totals are recorded in the Draft PR checks.

The full-repository Ruff command reports pre-existing style violations in historical files outside this change. Changed BUILD-088E and knowledge-publication scope passes Ruff. The known BUILD-085 failure replaces the child process environment with only `PYTHONPATH` on Windows and is unchanged by BUILD-088E.

## Regression summary

The required CI workflow runs BUILD-088E against PostgreSQL 16 and runs BUILD-088B, BUILD-088C, and BUILD-088D PostgreSQL tests in an isolated database. Local full-suite validation covers BUILD-082 through BUILD-088, Knowledge Graph, genus traversal, and public routes through the repository-wide test collection.

## Operational readiness

Readiness is fail-closed. A healthy report requires complete provenance coverage, continuous graph lineage, coherent rollback and projection state, complete audit records, valid immutable registries/lifecycle history, and the required migration/index/constraint state. No automatic destructive repair exists.

## Known limitations

- Latency observations describe the bounded validation corpus and are not production capacity claims.
- Downstream consumer execution and continuous monitoring remain deployment concerns; BUILD-088D continues to produce the immutable impact work records.
- Legacy graph writers identified by BUILD-088A/C remain outside this integration surface and require the previously approved deployment-role governance before production enablement.

## Future work

Production rollout may add monitoring/export adapters around the structured report, establish workload-specific latency objectives, and complete least-privilege database-role enforcement. These must consume the existing readiness contract and may not bypass governed publication.
