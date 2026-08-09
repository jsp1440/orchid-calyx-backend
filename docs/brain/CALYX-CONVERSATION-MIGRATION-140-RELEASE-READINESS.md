# CALYX Conversation Migration 140 — Release Gate

Status: **NOT READY FOR PRODUCTION AUTHORIZATION / NON-MUTATING VALIDATION COMPLETE**

Canonical CALYX-CONV code merge: PR #798, squash SHA `3c93b4a9f296762bb93582968bab1e7b9618f664`.
Canonical main used as the clean validation base: `6daef86a171f962604cc84f72ec26c19169bbf57`.
Validation-only PR: #804, exact validation head `5f40aca2f7de0599c6c8c5786ac9a44605134aa3`.
Superseded validation PR #801 was closed unmerged after workflow-provenance `action_required` produced zero jobs; no production action occurred.

This record distinguishes disposable validation from production observation. It does **not** authorize migration 101, migration 140, production deployment, production database mutation, Candidate Knowledge promotion, scientific publication, taxonomy activation, or Knowledge Graph mutation.

## Evidence-state vocabulary

- **VALIDATED** — deterministic code/file identity or static contract checked.
- **VERIFIED IN DISPOSABLE POSTGRESQL** — behavior observed in disposable PostgreSQL.
- **VERIFIED READ-ONLY IN PRODUCTION** — fact observed from production through a server-enforced read-only session.
- **PROPOSED** — future release mechanism/sequence not yet exercised in production.
- **UNVERIFIED** — required fact has not been empirically established.
- **BLOCKED** — a release prerequisite is currently unsatisfied.
- **AUTHORIZED** — explicitly approved governance action.
- **NOT AUTHORIZED** — action remains outside current authority.

## Migration identity — VALIDATED

File: `migrations/140_calyx_conversation_sessions.sql`.

- Git blob SHA: `f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf`.
- SHA-256: `38f2f6cc2cb2690f727329076d205bc5e0d79e98dcabc76a676f4b2908fde2f3`.
- The validation workflow rejects any migration-140 blob that differs from this exact identity.
- Migration bytes were not modified during this validation cycle.

## Disposable PostgreSQL lifecycle — VERIFIED IN DISPOSABLE POSTGRESQL

Clean validation workflow run: `31332084693`.

Matrix results:

- PostgreSQL 15 — complete disposable lifecycle **PASS**.
- PostgreSQL 16 — complete disposable lifecycle **PASS**.
- PostgreSQL 17 — complete disposable lifecycle **PASS**.
- PostgreSQL 17 container version observed: `17.10 (Debian 17.10-1.pgdg13+1)`, matching the production major/minor version family currently observed.

Exact PostgreSQL-17 receipt status: `VERIFIED_IN_DISPOSABLE_POSTGRESQL`.

All lifecycle stages passed:

1. `prerequisite_101` — PASS.
2. `apply_transactional` — PASS.
3. `valid_insert` — PASS.
4. `governance_and_append_only` — PASS.
5. `explicit_application_role_simulation` — PASS.
6. `reapply_idempotency` — PASS.
7. `malformed_existing_state_detection` — PASS.
8. `transaction_rollback` — PASS.
9. `final_canonical_state` — PASS.

### Schema postconditions — VERIFIED IN DISPOSABLE POSTGRESQL

After migration 140:

- `research_station.conversation_sessions` exists with the canonical columns/types.
- `research_station.conversation_messages` exists with the canonical columns/types.
- `conversation_sessions.conversation_id` is the primary key.
- `conversation_messages.message_id` is the primary key.
- `conversation_sessions.project_id` references `research_station.projects(project_id)`.
- `conversation_messages.conversation_id` references `research_station.conversation_sessions(conversation_id)`.
- `idx_rs_conversation_owner_project_updated` exists.
- `idx_rs_conversation_messages_session_time` exists.
- `research_station.reject_conversation_message_mutation()` exists.
- `rs_conversation_messages_immutable` is bound to `research_station.conversation_messages` for UPDATE/DELETE rejection.
- PUBLIC table privileges on the two migration-140 tables are absent.

### Governance constraints — VERIFIED IN DISPOSABLE POSTGRESQL

Observed fail-closed behavior:

- invalid `data_status` rejected with SQLSTATE `23514`;
- `evidence_authority=true` rejected with SQLSTATE `23514`;
- `scientific_publication_authorized=true` rejected with SQLSTATE `23514`;
- `knowledge_graph_mutation_authorized=true` rejected with SQLSTATE `23514`.

The canonical final constraints include:

- `data_status = 'CONVERSATION_CONTEXT'`;
- `evidence_authority = false`;
- `scientific_publication_authorized = false`;
- `knowledge_graph_mutation_authorized = false`.

### Append-only behavior — VERIFIED IN DISPOSABLE POSTGRESQL

- valid message INSERT succeeds;
- message UPDATE rejected by trigger, SQLSTATE `P0001`;
- message DELETE rejected by trigger, SQLSTATE `P0001`;
- failed UPDATE/DELETE do not alter the persisted message.

### Foreign-key behavior — VERIFIED IN DISPOSABLE POSTGRESQL

- valid Research Workspace project reference succeeds;
- nonexistent project reference rejected with SQLSTATE `23503`;
- valid session/message relationship succeeds.

### Application-role simulation — VERIFIED IN DISPOSABLE POSTGRESQL

A disposable non-login `calyx_app_validation` role was granted explicit schema/table permissions, switched into with `SET LOCAL ROLE`, and successfully performed intended read/insert behavior. Grants were then revoked and the disposable role removed. This validates PostgreSQL permission mechanics only; it does **not** establish the actual production application role or authorize privilege changes.

### Reapply/idempotency — VERIFIED IN DISPOSABLE POSTGRESQL

A second execution of the exact migration against the already canonical schema completed successfully and the complete structural/governance contract remained intact.

Idempotency is therefore verified only for an absent-or-canonical schema. `IF NOT EXISTS` is not treated as proof that a pre-existing object is correct.

### Malformed-existing-state detection — VERIFIED IN DISPOSABLE POSTGRESQL

The validator deliberately created incomplete migration-140 target tables and classified that state as `MALFORMED_PARTIAL` before migration execution. Release preflight additionally checks required columns/types and, when both target tables exist, required PK/FK/check constraints, indexes, append-only function/trigger, PUBLIC privilege state, and database-wide collision of the trigger name `rs_conversation_messages_immutable`.

A malformed, partial, or conflicting pre-existing target is an ABORT condition; the release process must not rely on `IF NOT EXISTS` to conceal it.

### Transaction rollback — VERIFIED IN DISPOSABLE POSTGRESQL

Migration 140 was executed inside an explicit PostgreSQL transaction, structural postconditions were checked, then an intentional safe failure was raised before commit. The transaction rolled back and both migration-140 target tables were confirmed absent afterward. A fresh subsequent transactional apply restored the canonical state.

## Production read-only preflight — VERIFIED READ-ONLY IN PRODUCTION

Production preflight used the repository `DATABASE_URL` secret and a connection forced with `default_transaction_read_only=on`. The script verified `SHOW transaction_read_only = on` before catalog inspection and performed no production mutation.

Observed production state on 2026-08-09:

- PostgreSQL: `17.10 (29ad1b7)` / `server_version_num=170010`.
- current/session database role: `neondb_owner`.
- `pgcrypto`: installed, version `1.3`.
- `research_station` schema: **ABSENT**.
- `research_station.projects`: **ABSENT**.
- migration-101 prerequisite compatibility: **FALSE**.
- `research_station.conversation_sessions`: **ABSENT**.
- `research_station.conversation_messages`: **ABSENT**.
- migration-140 target state: `ABSENT` (not partial).
- `research_station.reject_conversation_message_mutation()`: absent, as expected before migration 140.
- database-wide `rs_conversation_messages_immutable` trigger collision: none observed.
- production mutation attempted: **FALSE**.
- production mutation authorized: **FALSE**.

Fail-closed production-preflight status: `FAILED_INCOMPATIBLE_PRODUCTION_STATE` with blocker `MIGRATION_101_PREREQUISITE_INCOMPATIBLE`.

This is a release blocker, not a migration-140 implementation defect. Migration 140 contains a foreign key to `research_station.projects`; therefore it cannot be applied successfully as a standalone production migration while migration 101 is absent.

### Production drift findings

The important drift relative to the planned migration-140 prerequisite state is that the entire `research_station` foundation is absent in production. No conflicting migration-140 target tables, indexes, constraints, target function, or immutable-trigger-name collision were observed.

The actual production application role required for normal CALYX-CONV traffic is **UNVERIFIED**. The read-only preflight established the connected release/catalog role (`neondb_owner`) but did not discover a Research Station table-grantee role because the schema does not yet exist.

## Canonical serialization / activation infrastructure

### Existing serialization mechanism — VALIDATED

`scripts/run_with_postgres_validation_lock.py` serializes approved shared-database validation scripts using PostgreSQL session advisory lock `82078079` (`pg_advisory_lock` / `pg_advisory_unlock`). This is an existing canonical lock pattern, but its current allow-list is explicitly validation-only.

### Existing guarded activation mechanism — VALIDATED

`scripts/activate_reasoning_prerequisite_schemas.py` already provides important canonical release controls:

- default read-only preflight;
- explicit `--apply` requirement;
- exact confirmation environment value;
- pinned Git blob identities;
- preflight classification;
- migration-order recording;
- before/after contract inspection;
- mutation/partial-application evidence flags;
- hashed JSON evidence receipt.

It includes migration 101 in a larger prerequisite chain.

### Transaction deficiency — BLOCKED / PROPOSED CORRECTION

The current guarded activation script connects with `autocommit=True` and executes its migrations one-by-one. Earlier migrations can therefore remain committed if a later migration fails. It also does not include migration 140 or run migration-140 structural/behavioral postconditions inside the same transaction before commit.

Therefore the existing production activation path does **not yet satisfy** the CALYX-CONV release requirement for atomic prerequisite/schema activation.

Minimal future change — **PROPOSED, NOT AUTHORIZED**:

- extend the existing guarded activation infrastructure rather than create a second migration framework;
- add a target-scoped Research Station activation path for exact migration 101 + exact migration 140;
- use an approved production migration advisory/deployment lock (do not silently repurpose the validation-only allow-list without review);
- open one explicit database transaction;
- repeat prerequisite/target preflight inside the lock/transaction;
- execute pinned migration 101 if and only if its governed activation is authorized and required;
- execute pinned migration 140;
- run the complete migration-140 structural/governance/privilege/trigger postconditions before commit;
- COMMIT only if all postconditions pass;
- otherwise ROLLBACK the complete 101→140 transaction;
- emit the established receipt/evidence format.

This production-capable extension has not been authorized, merged, or executed against production in this cycle.

## Deployment ordering — PROPOSED

After a future schema-activation authorization and only if its postconditions pass:

1. final read-only preflight;
2. acquire canonical production migration serialization mechanism;
3. `BEGIN`;
4. recheck migration-101 and migration-140 contracts;
5. execute exact authorized prerequisite migration(s) and exact pinned migration 140 in governed order;
6. run structural, authority, privilege, FK, trigger, and append-only postconditions before commit;
7. `COMMIT` only on complete success;
8. verify committed schema read-only;
9. under separate deployment authorization, deploy/enable the CALYX-CONV application revision;
10. run authenticated controlled smoke tests;
11. observe logs/errors/authority invariants;
12. fail closed and withhold/disable capability if any postcondition or smoke test fails.

Code merge, schema activation, and application deployment remain separate governance actions.

## Post-deployment smoke-test plan — PROPOSED / NOT AUTHORIZED

Authenticated owner-scoped checks after a separately authorized deployment:

1. create projectless and project-scoped conversations;
2. list/get and verify cross-owner isolation;
3. persist an exchange and verify exactly two append-only context messages;
4. verify evidence/publication/KG authority flags remain false;
5. export Markdown from persisted transcript without retrieval rerun;
6. verify exact active-document scope and negative revision/parent namespace collisions;
7. save an exact persisted source to a project;
8. verify different-revision conflict fails closed;
9. verify authenticated Ask traffic remains absent from the unauthenticated legacy transcript;
10. verify deployed Mission Control exposes source linking;
11. verify no publication or Knowledge Graph mutation action is emitted.

## Abort conditions

Abort schema activation before commit on any of the following:

- migration 101 is absent without explicit authorization to activate it;
- migration-101 objects are malformed or conflict with the canonical contract;
- migration-140 target tables are partial, malformed, or unexpectedly populated/configured;
- migration 140 bytes differ from Git blob `f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf` or SHA-256 `38f2f6cc2cb2690f727329076d205bc5e0d79e98dcabc76a676f4b2908fde2f3`;
- approved serialization lock cannot be acquired or concurrent schema work cannot be excluded;
- transaction boundary cannot encompass the complete authorized prerequisite→140 sequence and postconditions;
- required PK/FK/check constraints or indexes are missing;
- evidence/publication/KG authority constraints are absent or permissive;
- append-only function/trigger is absent, misbound, ineffective, or its trigger name collides elsewhere;
- PUBLIC privileges are broader than intended;
- intended production application role/privileges are unknown or incompatible;
- any SQL error or postcondition failure occurs;
- application revision is incompatible with the committed schema;
- owner-authentication/Mission Control smoke tests fail;
- any publication or Knowledge Graph authority regression appears.

Before commit, any failure must roll back the entire active schema transaction. After commit and before production traffic, withhold application enablement if verification fails. Once production writes can exist, destructive table rollback is not automatic or pre-authorized; preserve data and use a separately reviewed corrective migration.

## Release decision

**NOT READY FOR PRODUCTION AUTHORIZATION.**

Reasoning:

- migration 140 itself is VERIFIED IN DISPOSABLE POSTGRESQL on PG15/16/17, including PG17.10;
- production was VERIFIED READ-ONLY on PG17.10;
- production migration-140 targets are cleanly absent, with no trigger-name collision;
- however the mandatory migration-101 Research Station foundation is absent in production;
- the current canonical guarded activation script uses per-migration autocommit and cannot yet provide the required atomic 101→140 + postconditions-before-commit guarantee;
- the actual production application role/privilege contract remains unverified because the Research Station schema is absent.

Accordingly, authorizing migration 140 alone would be invalid. A future governance package must first present a reviewed, validated, atomic extension of the existing activation infrastructure and explicitly request authorization for the required Research Station prerequisite activation plus migration 140. Production deployment must remain a separate authorization.

## Current governance state

- Migration 101 production activation: **NOT AUTHORIZED**.
- Migration 140 production activation: **NOT AUTHORIZED**.
- CALYX-CONV production deployment/enablement: **NOT AUTHORIZED**.
- Production database mutation performed by this validation cycle: **NONE**.
- Candidate Knowledge promotion: **NOT AUTHORIZED / NONE**.
- Scientific publication: **NOT AUTHORIZED / NONE**.
- Taxonomy activation: **NOT AUTHORIZED / NONE**.
- Production Knowledge Graph mutation: **NOT AUTHORIZED / NONE**.
