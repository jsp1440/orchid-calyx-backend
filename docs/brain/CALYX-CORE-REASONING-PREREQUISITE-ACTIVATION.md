# CALYX Core — Reasoning prerequisite activation

## Purpose

Close the production dependency gap discovered by the protected read-only Reasoning Ledger schema preflight without granting publication or Knowledge Graph mutation authority.

## Live production evidence

On 2026-08-08, temporary diagnostic PR #663 executed `scripts/activate_reasoning_publication_schemas.py` in its default read-only mode under the protected `production` environment.

Observed state:

- `activation_required=true`
- `ready_to_apply=false`
- `apply_requested=false`
- no production mutation attempted, authorized, or observed
- publication authorization false
- Knowledge Graph mutation authorization false
- migration 103 and 105 identities matched the pinned repository artifacts
- Reasoning Ledger and reasoning-publication target relations were absent
- blockers:
  - `PREREQUISITE_MISSING:oc_knowledge_publication.publication_candidates`
  - `PREREQUISITE_MISSING:research_station.projects`

The diagnostic PR was closed unmerged after evidence capture.

## Dependency chain

The existing disposable-PostgreSQL CALYX-BRAIN-003 test establishes this ordered chain:

1. `087b_context_preserving_interpretation.sql`
2. `088b_publication_registry_policy_foundation.sql`
3. `088c_atomic_graph_transaction_publication_engine.sql`
4. `088d_publication_lifecycle_corrections_rollback.sql`
5. `101_research_workspace_foundation.sql`
6. `103_reasoning_ledger.sql`
7. `104_orchid_continuum_brain.sql`
8. `105_reasoning_ledger_publication_adapter.sql`

Migration 103 requires `research_station.projects`; migration 105 additionally requires `oc_knowledge_publication.publication_candidates`.

## Implementation

Issue #665 introduces a dedicated prerequisite activation gate covering only migrations 087b, 088b, 088c, 088d, and 101.

The gate:

- defaults to read-only preflight;
- pins exact Git blob identities and SHA-256 fingerprints;
- verifies required table columns and governance functions/triggers;
- distinguishes a fresh database, safe resumable prefix, malformed partial schema, out-of-order publication foundation, and complete prerequisite foundation;
- requires both `--apply` and the exact confirmation token for mutation;
- records per-migration completed/failed state and partial application truthfully;
- verifies the schema again after application;
- never applies migrations 103 or 105;
- never publishes a Reasoning Ledger;
- never activates taxonomy;
- never mutates the production Knowledge Graph.

The protected production workflow uses the GitHub `production` environment and checks out exact current `main`. After an explicitly authorized prerequisite application, it runs the existing 103/105 gate in **read-only mode** to show whether issue #580 can advance.

## Corrective validation history

Validation was intentionally fail-first:

1. The first run stopped at Ruff formatting before PostgreSQL execution; formatting was corrected without changing behavior.
2. The next PostgreSQL run exposed test contamination because a malformed-schema test reused a database where the successful apply test had already created `research_station.projects`. The malformed simulation was moved into a rollback-only transaction so it no longer changes shared disposable state.
3. The next run proved the test-level apply/replay path but exposed a workflow-ordering defect: the independent CLI apply was being executed against the already-complete test database. The validation workflow now resets the disposable database before the CLI rehearsal, creating two independent proofs instead of weakening the activation command.

Validated code/workflow head before this documentation receipt: `5d78dc34bf0b03629e25f66915cc6156f0bc62d0`.

Passing evidence:

- CALYX Reasoning Prerequisite Activation Validation run #5 — success
  - compile, Ruff, and format checks passed
  - 7 focused tests passed
  - ordered 087b→088b→088c→088d→101 application passed on PostgreSQL 16
  - direct DDL replay remained idempotent
  - malformed partial schema failed closed
  - fresh independent CLI preflight passed
  - fresh independent CLI apply passed
  - explicit verification proved Reasoning Ledger 103 and publication 105 target relations remained absent
  - disposable evidence artifacts uploaded
- CALYX Workflow Governance Audit run #489 — success
- BUILD-088E Validation run #1238 — success

## Governance separation

There are three independent production decisions:

1. apply prerequisite migrations 087b→088d plus 101;
2. later apply Reasoning Ledger/publication migrations 103→105;
3. later publish one reviewed ledger into the versioned Knowledge Graph.

Authorization for one does not imply authorization for either later step.

Opening or merging the #665 implementation PR does not authorize production database mutation. The agent must stop before merge and before production application unless the owner explicitly authorizes those actions.
