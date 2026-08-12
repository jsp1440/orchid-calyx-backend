# CALYX Live Conversation — Clean Atomic 101→140 Validation

Status: **CURRENT-MAIN CLEAN RECONSTRUCTION / NON-PRODUCTION / EXACT-HEAD EXECUTABLE VALIDATION BLOCKED BEFORE STEP 1**

PR: #905
Base: `60c5756d84afb53587cc2a8e567aa84a33b44d23`
Atomic reconstruction commit: `445c91296ba5bcc1661c40bf7f738198fdaf4f8c`
Latest pre-documentation code head: `4857353f838b5a7855a9ee4647f9712d61a06499`

## Scope

This branch carries only the previously executable-green Research Station migration 101→140 activation capability:

- guarded `research-station-conversations` profile on the existing activation CLI;
- exact migration 101 and 140 identity checks;
- explicit single transaction through migration postconditions;
- transaction-scoped advisory serialization on lock `82078079`;
- rollback on injected failures;
- canonical rerun/no-op behavior;
- canonical migration-101-only resume by applying only migration 140;
- malformed/partial schema refusal;
- foreign-key, authority-constraint, append-only, index/default/nullability, and PUBLIC-privilege checks;
- disposable PostgreSQL 15/16/17 validation.

The historical reasoning-prerequisite profile remains the default and is still validated by the same workflow.

## Current-main convergence

The reconstruction is one runtime/workflow commit directly on the canonical base. Relative to that base, the effective code surface is exactly four files:

1. `.github/workflows/calyx-reasoning-prerequisite-activation-validation.yml`;
2. `scripts/activate_reasoning_prerequisite_schemas.py`;
3. `scripts/research_station_conversation_activation.py`;
4. `tests/test_research_station_conversation_atomic_activation.py`.

The shared guarded CLI changes by only the explicit profile hook; the historical reasoning path remains otherwise intact. No protected production workflow or runtime/migration target verifier is included.

## Authority split

PR #897 (or its canonical successor) is the sole authority for proving deployed-runtime and migration database target equivalence. This branch deliberately does **not** carry `verify_calyx_runtime_database_target.py` or any competing database-target proof.

The protected production activation workflow is deliberately not changed in this reconstruction. Production wiring must depend on the canonical target-equivalence gate and receive separate governed authorization.

## Prior executable evidence

The identical atomic implementation/test/workflow source files were executable-green at historical head `7a1a22affde15b9c675da09039d6828bbefdd812` across PostgreSQL 15/16/17, including rollback, rerun/no-op, 101-only resume, and governance behavior. That historical evidence is source-material confidence only; this current-main reconstruction still requires exact-head execution before integration.

## Exact-head validation attempt

Code head `4857353f838b5a7855a9ee4647f9712d61a06499` triggered:

- CALYX Reasoning Prerequisite Activation Validation — run `31595533730`;
  - historical/default validation job `94109999466`: `steps=null`;
  - PG16 job `94109999477`: `steps=null`;
  - PG17 job `94109999526`: `steps=null`;
  - PG15 job `94109999539`: `steps=null`;
- BUILD-088E — run `31595533676`, job `94109999189`: `steps=null`.

No checkout, Python setup, migration identity check, Ruff, pytest, PostgreSQL test, or application command executed. This is infrastructure non-execution, not a code/test verdict. Do not blind-rerun; a private job with a non-empty step list is the recovery signal.

No inline review threads are currently open on PR #905.

## Talk-to-Calyx frontend integration dependency

Research Station PR #19 independently contains the current frontend acceptance lane. A shell audit found and fixed a last-mile routing defect: `/workspace` previously rendered its nested `<Outlet />` only for `/workspace/projects`, potentially hiding matched `/workspace/calyx/$projectId`, `/workspace/calyx/$projectId/sources`, and `/workspace/analysis/$projectId` pages behind the hash-driven dashboard. The branch now recognizes all nested workspace route families and carries focused route coverage. Its current exact-head runner also fails before checkout with `steps=null`.

## Governance

No production migration, deployment, persistent-conversation traffic, Candidate Knowledge promotion, scientific publication, taxonomy activation, or production Knowledge Graph mutation is authorized or performed.
