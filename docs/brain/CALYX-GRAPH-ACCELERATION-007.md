# CALYX-GRAPH-ACCELERATION-007 — Brain Implementation Record

Date: 2026-08-06
Repository: `jsp1440/orchid-calyx-backend`
Tracking issue: #458
Pull request: #460

## Objective

Move the Knowledge Graph and Brain integration from structurally connected code toward safe, observable operation without authorizing production graph mutation or automatic scientific publication.

## Completed implementation

1. Normalized null Knowledge Graph edge source identities to a non-null sentinel so SQLite uniqueness and second-pass idempotency behave correctly.
2. Added a migration path for existing staging databases whose edge schema allowed null source identities.
3. Added per-session resume locking so concurrent operator requests cannot corrupt or permanently fail a dry run.
4. Added bounded stale-lock recovery.
5. Prevented read-only status and cancellation reporting from materializing empty SQLite staging databases.
6. Added dry-run progress telemetry: completed domains, total domains, batches, active domain, active pass, source offset, lock state, and next action.
7. Corrected deployed smoke authentication to require a real bearer token and reject the historical `cookie` sentinel.
8. Moved health verification ahead of owner-credential validation and added step-labelled network and HTTP failures.
9. Added the governed Brain Candidate Knowledge handoff route to deployment preflight requirements.
10. Added regression coverage and dedicated Knowledge Graph CI inclusion.

## Scientific governance state

- Production graph mutation: disabled.
- Automatic Candidate Knowledge publication: disabled.
- Human review: required.
- Taxonomy promotion: not authorized.
- Live dry run: not started by this implementation.

## Operational next gate

The exact PR head must pass both the dedicated Knowledge Graph workflow and the broad validation workflow. After merge and deployment, the owner-authenticated deployment preflight must report `ready_for_live_resumable_dry_run: true` before a bounded live dry run begins.

## Completion evidence

Implementation is contained in PR #460. This record is intentionally committed with the implementation so the Brain has a durable account of what changed, what remains prohibited, and the next operational gate.
