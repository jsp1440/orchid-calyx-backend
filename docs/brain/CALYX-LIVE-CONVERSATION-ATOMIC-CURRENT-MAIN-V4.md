# CALYX Live Conversation — Atomic 101→140 Current-Main Validation

Status: **VALIDATED IN DISPOSABLE POSTGRESQL / READY FOR REVIEW / PRODUCTION ACTIVATION NOT AUTHORIZED**

## Integration authority

PR #960 is the clean current-main reconstruction of the Research Station conversation schema activation path.

Validated code head: `c302b087fe3f5a7fbf5d63f415b9fe720328912c`.

Base used for reconstruction: `3a17f706fef2ba72ee5fb1576b63e7e13a42b748`. Before PR creation, canonical `main` advanced by one documentation-only commit (`docs/brain/CALYX-HARVEST-006-LITERATURE-FAIRNESS.md`); no atomic-runner file overlap occurred, and GitHub reports PR #960 mergeable against the current base.

## Executable validation

Exact code-head workflows:

- CALYX Reasoning Prerequisite Activation Validation — run `31764504192` — **PASS**.
- BUILD-088E Validation — run `31764504315` — **PASS**.
- CALYX Workflow Governance Audit — run `31764504135` — **PASS**.

The dedicated activation run passed all four jobs:

- historical/default reasoning-prerequisite profile — **PASS**;
- Research Station atomic activation PostgreSQL 15 — **PASS**;
- PostgreSQL 16 — **PASS**;
- PostgreSQL 17 — **PASS**.

Each Research Station matrix job passed:

- exact migration-101 and migration-140 identity checks;
- compile, Ruff lint and Ruff formatting;
- focused atomic transaction / rollback / serialization / governance regressions;
- read-only disposable preflight;
- atomic disposable apply;
- evidence artifact upload.

## Validated behavior

The current-main slice preserves the existing guarded activation CLI and adds the explicit `research-station-conversations` profile. It validates:

- exact migration 101 / 140 bytes;
- one PostgreSQL transaction through both migration postconditions;
- transaction-scoped advisory serialization on lock `82078079`;
- rollback after intentional failure after migration 101 or 140;
- canonical rerun/no-op;
- canonical migration-101-only resume by applying only migration 140;
- malformed/partial-state refusal;
- project/session/message foreign-key behavior;
- conversation-context and false evidence/publication/KG authority constraints;
- append-only conversation messages;
- required indexes, defaults, nullability and PUBLIC privilege expectations.

The historical reasoning-prerequisite profile remains the default CLI behavior and passed its existing validation unchanged.

## Authority split

Runtime-vs-migration database-target equivalence is **not** owned by PR #960. That release proof remains the responsibility of PR #897 or its clean current-main successor. PR #960 intentionally does not carry the obsolete target verifier from historical PR #819 and does not modify protected production activation wiring.

## Production status

NOT AUTHORIZED / NOT PERFORMED:

- production migration 101;
- production migration 140;
- production database mutation;
- persistent-conversation production traffic;
- production deployment;
- Candidate Knowledge promotion;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation.

## Next release dependency

Reconstruct and executable-validate the read-only runtime/migration database-target equivalence gate on current canonical `main`. Only after both the schema activation mechanism and database-target proof are current-main validated should a production schema-activation authorization package be considered.
