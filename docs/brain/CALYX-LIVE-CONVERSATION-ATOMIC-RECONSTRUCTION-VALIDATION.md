# CALYX Live Conversation — Clean Atomic 101→140 Validation

Status: **CURRENT-MAIN CLEAN RECONSTRUCTION / NON-PRODUCTION / VALIDATION REQUIRED**

Base: `60c5756d84afb53587cc2a8e567aa84a33b44d23`
Atomic reconstruction commit: `445c91296ba5bcc1661c40bf7f738198fdaf4f8c`

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

## Authority split

PR #897 (or its canonical successor) is the sole authority for proving deployed-runtime and migration database target equivalence. This branch deliberately does **not** carry `verify_calyx_runtime_database_target.py` or any competing database-target proof.

The protected production activation workflow is deliberately not changed in this reconstruction. Production wiring must depend on the canonical target-equivalence gate and receive separate governed authorization.

## Prior executable evidence

The identical atomic implementation/test/workflow source files were executable-green at historical head `7a1a22affde15b9c675da09039d6828bbefdd812` across PostgreSQL 15/16/17, including rollback, rerun/no-op, 101-only resume, and governance behavior. That historical evidence is source-material confidence only; this current-main reconstruction still requires exact-head execution before integration.

## Governance

No production migration, deployment, persistent-conversation traffic, Candidate Knowledge promotion, scientific publication, taxonomy activation, or production Knowledge Graph mutation is authorized or performed.
