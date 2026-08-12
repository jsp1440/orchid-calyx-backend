# CALYX Live Conversation — Atomic 101→140 Reconstruction

Status: **RECONSTRUCTION REQUIRED / NON-PRODUCTION / NO MERGE OR DEPLOY AUTHORITY**

## Purpose

Preserve the validated Research Station migration 101→140 activation capability on current canonical main without carrying the competing runtime/migration database-target verifier that accumulated on closed PR #819.

## Authority split

- A clean current-main reconstruction should own only migration 101→140 schema-contract inspection, atomic transaction/rollback, advisory serialization, disposable PostgreSQL validation, and guarded CLI profile integration.
- PR #897 (or its canonical successor) remains the sole authority for deployed-runtime versus migration-database target equivalence.
- Closed PR #819 is historical validation/review evidence only and must not be merged.

## Validated baseline retained as source material

Previously executable-green atomic head: `7a1a22affde15b9c675da09039d6828bbefdd812`.

That head had executable PostgreSQL 15/16/17 validation for pinned 101/140 migration bytes, single-transaction activation, advisory serialization, rollback, canonical re-run/no-op, migration-101-only resume, malformed-state refusal, governance/append-only behavior, index/default/nullability checks, PUBLIC privilege checks, and truthful disposable-versus-production receipt semantics.

Later strict CHECK/index hardening on #819 requires a clean reconstruction and fresh exact-head execution before it can become integration authority.

## Talk-to-Calyx frontend finding

Research Station PR #19 now contains a fix for a separate last-mile routing defect: the `/workspace` shell previously rendered its router outlet only for `/workspace/projects`, which could hide matched `/workspace/calyx/$projectId`, `/workspace/calyx/$projectId/sources`, and `/workspace/analysis/$projectId` pages behind the hash-driven dashboard. The branch now recognizes all nested workspace route families and carries regression coverage. Exact-head hosted CI is still blocked by zero-step runner allocation.

## Governance

NOT AUTHORIZED / NOT PERFORMED:

- production migration 101 or 140;
- production deployment;
- persistent-conversation production traffic;
- Candidate Knowledge promotion;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation.
