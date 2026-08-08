# CALYX CORE — Durable occurrence staging

Date: 2026-08-07
Issue: #386
Parent: #384

## Why this slice exists

The deployed `calyx-production-certification-v1` report identified three concrete occurrence blockers on the live backend:

1. Harvester V2 had no durable production persistence implementation;
2. Harvester V2 had no durable checkpoint store for occurrence staging;
3. GBIF/iNaturalist identifiers were not durably reconciled to canonical taxon IDs before staging projection, and unresolved taxa needed an explicit review queue.

Current `runtime/occurrence_staging.py` already provides bounded normalization, checksum deduplication and injectable canonical-name reconciliation. This build does not replace that logic. It gives the existing staging contract a durable PostgreSQL boundary.

## Implemented contract

Migration `106_occurrence_staging_runtime.sql` creates the isolated `occurrence_pipeline` schema with three additive tables:

- `staged_occurrences` — durable normalized occurrence payload plus preserved raw source payload, canonical taxon ID, reconciliation state and acquisition checksum;
- `checkpoints` — durable source/job batch position and resumability state;
- `review_queue` — durable unmatched or unresolved taxon reconciliation work.

`runtime/occurrence_persistence.py` adds `PostgresOccurrenceStagingStore` and `stage_and_persist_occurrences()`.

The bounded orchestration sequence is:

`normalized source batch → load durable checkpoint → load durable seen checksums → existing occurrence staging/reconciliation → transactional staged/review/checkpoint persistence`

## Idempotency and recovery

- Source record identity is unique on `(source, source_record_id)`.
- Acquisition checksum is unique within a source.
- Durable seen checksums feed the existing staging deduplicator.
- A deliberate replay may supply its original `batch_start`; replay produces zero new staged deltas.
- If `batch_start` is omitted, a restarted process resumes from the durable checkpoint's prior `batch_end`.
- Staged rows, review items and checkpoint advancement are committed in one database transaction.

## Provenance and reconciliation

For every staged occurrence the store preserves:

- source and source record ID;
- scientific and accepted names;
- source taxon key;
- canonical taxon ID when resolved;
- explicit reconciliation state;
- coordinates/locality/date/collector/license/basis of record;
- raw source JSON;
- normalized staging JSON;
- deterministic acquisition checksum.

Unresolved taxa are not discarded or silently assigned. They remain staged with an explicit unresolved state and enter `occurrence_pipeline.review_queue` for human or governed reconciliation.

## Governance

This is a staging-only persistence layer. It does not:

- write to `oc_graph` or the production Knowledge Graph;
- activate taxonomy;
- approve a taxonomic reconciliation;
- publish scientific knowledge;
- start an unbounded harvester;
- deploy or apply the migration to production.

Issue #386 explicitly requires the agent to open a PR and stop before merge. Production migration or promotion is therefore outside this build.

## Validation

The dedicated `CALYX Occurrence Durable Staging Validation` workflow uses disposable PostgreSQL 16 and verifies:

- migration scope and additive-only behavior;
- raw + normalized durable persistence;
- canonical taxon ID persistence;
- unresolved-taxon review queue persistence;
- durable checkpoints across store/process restart;
- replay with zero duplicate staged deltas;
- automatic resume from prior durable checkpoint;
- existing Harvester V2 manager and GBIF plugin regressions;
- Ruff, compile, diff hygiene and explicit no-`oc_graph` mutation smoke.

Final exact-head run identifiers are recorded on PR #386's implementation PR before review disposition.
