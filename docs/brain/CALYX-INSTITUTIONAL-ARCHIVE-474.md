# CALYX-474 — Institutional archive activation and governed ingestion

Status: IMPLEMENTED / VALIDATION BLOCKED BY GITHUB HOSTED RUNNER / STAGING-READY ONLY

## Delivered

- Read-only activation certification for the existing BUILD-080 institutional archive subsystem rather than a competing importer.
- Exact migration/readiness inspection for all seven archive tables created by migration 106.
- Exact production-hardening inspection for the lease/dispatch/cancellation columns introduced by migration 107.
- Sanitized readiness evidence that reports only booleans, counts, missing schema elements, blockers, and a deterministic SHA-256 digest; it never returns `DATABASE_URL` values or approved filesystem paths.
- Evidence receipts registered through the existing immutable Calyx artifact registry.
- Explicit contract inventory for archive documents, files, entities, relationships, provenance, import runs, and checkpoints.
- Protected `/archive/activation/status`, `/archive/activation/contracts`, and `/archive/activation/evidence` endpoints using existing owner/API-key authentication.
- Regression assertions preserving bounded source-root imports, safe ZIP handling, duplicate detection, malformed-file continuation, durable checkpoints/resume, and canonical-graph non-mutation.
- Deterministic activation tests plus BUILD-080 migration and BUILD-080C hardening regression coverage.

## Integration model

CALYX-474 activates and certifies the archive system already delivered by BUILD-080/080C. Existing `ArchivePolicy` remains the filesystem authority: imports stay disabled until `ARCHIVE_ALLOWED_ROOTS` is configured, and only descendants of those approved roots may be imported. Existing `ArchiveScanner`, `ArchiveImporter`, `ArchiveRegistry`, checkpoint, provenance, entity, and relationship contracts remain authoritative.

Activation certification is deliberately read-only. It inspects PostgreSQL metadata to determine whether migration 106 and hardening migration 107 are present, but it does not run migrations, scan arbitrary filesystems, start imports, deploy code, or publish archive-local relationships to the canonical Knowledge Graph.

## Review hardening

Static review found that the original evidence digest included `generated_at`. Identical readiness state therefore produced a new digest and artifact ID on every request, contradicting the documented deterministic/content-addressed contract. Removing the timestamp from only the digest would also have caused an immutable-artifact conflict because the same artifact ID would still receive timestamp-varying bytes.

The repaired contract separates observation metadata from evidence identity:

- `generated_at` remains in the API observation;
- `evidence_digest` is computed only from stable readiness/governance state;
- immutable artifact content excludes `generated_at` and includes the stable evidence digest;
- repeated unchanged readiness registration returns the same artifact ID/checksum and an idempotent `created=false` replay.

A focused regression now performs two registrations against the same immutable registry and proves stable digest, artifact identity, checksum, and duplicate replay behavior while retaining path/credential sanitization.

## Readiness blockers

The activation surface reports exact blockers rather than guessing readiness:

- `DATABASE_NOT_CONFIGURED`
- `ARCHIVE_MIGRATION_106_NOT_CERTIFIED`
- `ARCHIVE_HARDENING_107_NOT_CERTIFIED`
- `ARCHIVE_ALLOWED_ROOTS_NOT_CONFIGURED`

An empty blocker list means the backend is structurally ready for a bounded, authenticated staging import. It is not production-import authorization.

## Governance boundaries

`production_import_authorized=false`, `graph_publication_authorized=false`, `deployment_authorized=false`, and `unrestricted_filesystem_scanning_authorized=false` are permanent in this build. A successful activation certificate does not authorize production import, migration execution, deployment, merge, or Knowledge Graph mutation.

## Validation

Dedicated CI compiles the activation/routes surface, runs CALYX-474 tests together with BUILD-080 migration and BUILD-080C archive-hardening regressions, asserts secret/path sanitization and permanent no-production-import/no-graph-publication boundaries, runs Ruff, and checks diff hygiene.

GitHub-hosted runner attempts on exact implementation heads have failed before any job step executed (`steps=null`), matching the contemporaneous repository-wide runner allocation incident tracked in #481. This is infrastructure failure rather than executed test evidence. No workflow assertion is weakened or bypassed; the repaired head remains draft until real executable validation succeeds.
