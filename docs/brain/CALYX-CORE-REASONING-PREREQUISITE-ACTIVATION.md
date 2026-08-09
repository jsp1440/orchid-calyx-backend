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

## Research Station 101→140 atomic validation extension

PR #819 is the clean current-main integration/validation authority for the `research-station-conversations` profile. Superseded PRs #816 and #818 are retained only as failure-first history.

The profile:

- pins migration 101 Git blob `3333853c97832154cb0f61bace0c2184396da160`;
- pins migration 140 Git blob `f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf`;
- serializes on PostgreSQL advisory-lock key `82078079`;
- applies 101→140 inside one transaction;
- verifies structural and governance postconditions before commit;
- safe-resumes from canonical 101-only state;
- no-ops on canonical 101+140 state;
- fails closed on malformed, partial, or out-of-order state;
- validates required types, nullability/defaults, PK/FK constraints, indexes, append-only triggers/functions, PUBLIC privilege state, and trigger-name collisions;
- injects failures after migration 101 and after migration 140 to prove complete rollback;
- uses only disposable PostgreSQL 15/16/17 validation databases.

### Failure-first corrections

The validation path surfaced and corrected the following defects before acceptance:

1. Ruff/style findings in the initial activation/test implementation.
2. Extraction of the Research Station implementation into `scripts/research_station_conversation_activation.py`, keeping `scripts/activate_reasoning_prerequisite_schemas.py` as the canonical guarded CLI/profile dispatcher.
3. SQL fixture formatting defects that prevented behavioral execution.
4. A test-harness import defect that prevented the standalone activation module from loading under pytest.
5. A migration-140 schema expectation mismatch: canonical `conversation_sessions.title` defaults to `'Calyx conversation'::text`.
6. A direct-script dispatcher import defect: `python scripts/activate_reasoning_prerequisite_schemas.py --profile research-station-conversations` could not resolve a package-style `scripts.*` helper import. The clean #819 lineage uses the repository's direct-script execution model and independently validates package-style test discovery.

### VALIDATED

Exact #819 code head `009dc4ceaad354797a8b699bc9e06bc8cd70fde8` passed every triggered release gate on 2026-08-09:

- CALYX Reasoning Prerequisite Activation Validation run `31333839697` — SUCCESS.
  - legacy prerequisite validation job — success;
  - PostgreSQL 15 Research Station 101→140 job — success;
  - PostgreSQL 16 Research Station 101→140 job — success;
  - PostgreSQL 17 Research Station 101→140 job — success.
- BUILD-088E Validation run `31333839704` — SUCCESS.
- CALYX Workflow Governance Audit run `31333839706` — SUCCESS.

The PG15/16/17 jobs each passed:

- pinned migration-byte verification;
- compile, Ruff lint, and format checks;
- atomic transaction / rollback / serialization / governance tests;
- disposable profile preflight through the real guarded CLI;
- disposable atomic apply through the real guarded CLI;
- evidence upload and clean container shutdown.

The legacy validation job independently passed its existing prerequisite tests, database reset, CLI preflight, CLI apply, and explicit proof that Reasoning Ledger migration 103 and publication migration 105 remain absent.

This validates the migration tooling and disposable transaction semantics only. It is not production migration evidence and does not authorize a production apply.

## Governance separation

There are independent production decisions:

1. apply prerequisite migrations 087b→088d plus 101;
2. apply Research Station conversation migration 140 where appropriate;
3. later apply Reasoning Ledger/publication migrations 103→105;
4. later publish one reviewed ledger into the versioned Knowledge Graph.

Authorization for one does not imply authorization for any later step.

Opening or merging validation/tooling code does not authorize production database mutation. Production Research Station migration 101/140 remains a separate governance decision. No scientific publication, taxonomy activation, Candidate Knowledge promotion, production Knowledge Graph mutation, deployment, or production write authority is granted by this validation.