# CALYX Conversation Migration 140 — Release Readiness

Status: PREPARED / NOT AUTHORIZED FOR PRODUCTION APPLY OR DEPLOYMENT

Canonical code merge: PR #798, squash SHA `3c93b4a9f296762bb93582968bab1e7b9618f664`.
Brain merged-state checkpoint commit: `673b8ea88c91f837e43dd2d1ecc129540911a207`.

This document is release-readiness preparation only. It does not authorize or execute migration 140, production deployment, production database mutation, Candidate Knowledge promotion, scientific publication, taxonomy activation, or Knowledge Graph mutation.

## Exact schema effects

Migration `migrations/140_calyx_conversation_sessions.sql`:

1. Ensures extension `pgcrypto` exists.
2. Ensures schema `research_station` exists.
3. Creates `research_station.conversation_sessions` when absent:
   - UUID primary key `conversation_id` using `gen_random_uuid()`;
   - required owner subject;
   - optional `project_id` foreign key to `research_station.projects(project_id)`;
   - title with 1..160 character check;
   - active taxon/document context fields;
   - created/updated/archive timestamps;
   - positive integer version;
   - owner/project/updated index.
4. Creates `research_station.conversation_messages` when absent:
   - UUID primary key `message_id`;
   - required foreign key to conversation session;
   - owner, role, content, epistemic status;
   - JSONB context/source/tool trace;
   - permanent `CONVERSATION_CONTEXT` status;
   - permanent false checks for evidence authority, scientific-publication authorization, and Knowledge Graph mutation authorization;
   - created timestamp;
   - session/time/message index.
5. Creates/replaces `research_station.reject_conversation_message_mutation()`.
6. Creates the `rs_conversation_messages_immutable` UPDATE/DELETE trigger when absent.
7. Revokes PUBLIC privileges from both conversation tables.

The SQLAlchemy canonical models in `app/conversation_memory/models.py` correspond to the two tables and their foreign-key/index structure. Database SQL adds stronger content/authority checks and the append-only trigger.

## Prerequisites

Mandatory before apply:

- Canonical application code must be the reviewed CALYX-CONV version or later compatible code.
- `research_station.projects` from migration 101 must exist and contain at least `project_id UUID` as the referenced primary/unique key. Migration 140 cannot create `conversation_sessions` successfully without this prerequisite.
- The executing database principal must be permitted to create the required tables/index/function/trigger and, if needed, `pgcrypto`.
- Migration-file identity must be pinned to the canonical repository blob before execution.
- Production schema must be inspected read-only for partial/conflicting objects before any mutation.

Required preflight object checks:

- `to_regclass('research_station.projects')` exists;
- `to_regclass('research_station.conversation_sessions')` and `conversation_messages` are either both absent or structurally complete;
- if either target table already exists, compare required columns, types, nullability, checks, foreign keys, indexes, and trigger state rather than relying on `IF NOT EXISTS`;
- verify no trigger-name collision can cause `rs_conversation_messages_immutable` to be skipped on the intended table;
- verify `research_station.reject_conversation_message_mutation` resolves in the intended schema;
- verify expected privileges/ownership before and after apply.

A malformed/partial target schema is an ABORT condition. Do not attempt to repair it implicitly with the migration file.

## Transaction behavior

The SQL file itself contains no explicit `BEGIN`/`COMMIT`. Release execution must therefore supply the transaction boundary.

Required production strategy:

1. Acquire the repository-approved migration serialization/advisory lock if the release mechanism provides one.
2. Start a single explicit database transaction.
3. Repeat the target-schema preflight inside the lock/transaction immediately before executing SQL.
4. Execute the exact pinned migration bytes.
5. Run structural and behavioral postconditions before commit.
6. Commit only if every postcondition passes.

Do not use a per-statement autocommit path for migration 140. Transaction-scoped DDL permits a failure before commit to roll back newly created tables, indexes, function, trigger, and privilege changes together.

## Idempotency and re-run safety

The migration is designed to be additive/re-runnable for a correctly absent-or-complete schema:

- extension/schema/table/index creation uses `IF NOT EXISTS`;
- the trigger function uses `CREATE OR REPLACE FUNCTION`;
- trigger creation checks for an existing trigger name;
- repeated REVOKE is safe.

However, `IF NOT EXISTS` does not validate an already-existing object's shape. Therefore idempotency is conditional: a second run is acceptable only after structural preflight proves existing objects match the canonical contract.

Release validation must include a disposable PostgreSQL apply + postcondition + second-apply + postcondition cycle before production authorization.

## Rollback / recovery strategy

### Before commit

Any SQL or postcondition failure inside the explicit transaction requires immediate transaction rollback. No application deployment should proceed.

### After commit

Preferred recovery is forward repair, not destructive automatic rollback, because persisted conversation records may exist after activation.

A destructive rollback (dropping the trigger/function/tables) is NOT pre-authorized and must never be automated once production writes may have occurred. If a post-commit defect is discovered:

1. disable/withhold the persistent-conversation application release path;
2. preserve database state and collect schema/data diagnostics;
3. determine whether any conversation rows were written;
4. prepare a separately reviewed corrective migration;
5. require explicit governance authorization before any destructive data/schema reversal.

## Expected production impact

Migration 140 is additive and does not rewrite existing Research Workspace, Candidate Knowledge, publication, taxonomy, or Knowledge Graph tables. Normal expected lock duration is limited to creation of two new tables, two indexes, one trigger function, one trigger, and privilege changes.

The foreign key to `research_station.projects` creates a dependency on that table and may take the catalog locks required to establish the constraint. No existing project rows are rewritten.

The app should not receive persistent-conversation traffic until migration postconditions pass, because conversation create/list/get/ask endpoints depend on these tables.

## Application / migration ordering

Recommended governed release order:

1. Confirm the production application revision that will be deployed includes canonical CALYX-CONV code.
2. Read-only production preflight for migration 101 prerequisite and absence/completeness of migration-140 objects.
3. Maintenance/release gate: prevent persistent-conversation traffic from reaching code that expects migration 140.
4. Apply migration 140 transactionally under the approved production migration mechanism.
5. Verify structural and append-only postconditions before commit.
6. Commit migration.
7. Run database-level smoke tests using rollbackable/test records or a release-specific safe fixture strategy.
8. Deploy/enable the CALYX-CONV application revision only under separate deployment authorization.
9. Run authenticated API smoke tests.
10. Observe metrics/logs before declaring persistent conversations operational.

Code merge alone is not production activation.

## Mandatory postconditions

Immediately after migration SQL and before/at release commit, verify:

- both tables exist in `research_station`;
- required columns/types/nullability/defaults are present;
- `conversation_sessions.project_id` references `research_station.projects(project_id)`;
- required indexes exist;
- authority CHECK constraints reject `TRUE` for evidence/publication/KG mutation fields;
- `data_status` rejects anything except `CONVERSATION_CONTEXT`;
- role constraint rejects values outside `OPERATOR`/`CALYX`;
- append-only trigger exists specifically on `research_station.conversation_messages`;
- a controlled UPDATE and DELETE attempt against a disposable conversation message are rejected by the trigger;
- table PUBLIC privileges are absent;
- a valid session/message insert succeeds under the intended application role;
- deleting/updating existing Research Workspace objects is not part of this migration.

## API smoke-test plan after separately authorized deployment

Authenticated owner-scoped tests:

1. create a conversation without a project;
2. create a conversation with an owned Research Workspace project;
3. list/get conversations and confirm cross-owner access is denied;
4. ask a persistent conversation and verify exactly two append-only context messages are persisted;
5. confirm `evidence_authority=false`, `scientific_publication_authorized=false`, and `knowledge_graph_mutation_authorized=false`;
6. export Markdown and verify it is rendered from persisted transcript/context without rerunning retrieval;
7. exercise exact active-document scope and verify revision/parent identifiers cannot satisfy document scope;
8. link a persisted source to the conversation project and verify exact document/revision identity;
9. verify an existing different revision fails closed with `CONVERSATION_SOURCE_PROJECT_LINK_IDENTITY_CONFLICT`;
10. verify authenticated Ask traffic does not appear in the unauthenticated legacy transcript;
11. verify the deployed Mission Control router exposes the source-link endpoint;
12. verify no publication or Knowledge Graph mutation operation is emitted.

## Observability / verification plan

Capture for the governed release record:

- migration file blob/SHA-256 identity;
- target environment/database identifier without leaking credentials;
- preflight schema contract report;
- transaction start/commit outcome;
- postcondition report;
- row counts for the two new tables immediately after migration and after smoke tests;
- trigger/function/index presence;
- application revision/SHA;
- authenticated smoke-test results and correlation IDs;
- error counts for conversation endpoints during the observation window;
- explicit confirmation that publication and Knowledge Graph mutation counters/actions remain unchanged.

## Abort / rollback conditions

Abort before commit/deployment on any of the following:

- migration 101 prerequisite absent or malformed;
- migration-140 target object partially exists or differs from canonical shape;
- migration file identity differs from reviewed canonical bytes;
- inability to create/verify the append-only trigger;
- authority checks missing or permissive;
- PUBLIC privileges remain broader than intended;
- SQL error or postcondition failure;
- concurrent migration/schema activity cannot be safely serialized;
- application revision is incompatible with the schema contract;
- required owner-authentication or Mission Control routes fail smoke tests;
- any evidence/publication/KG authority regression appears.

## Current release-readiness conclusion

Code-level schema and ORM compatibility is established. Migration 101 is the explicit schema prerequisite. Migration 140 remains **UNAPPLIED** and production deployment remains **NOT PERFORMED**.

Production compatibility is not yet empirically established because this cycle has not inspected or mutated the production database. Before a future production-apply authorization, the remaining mandatory evidence is:

- read-only production schema preflight;
- disposable PostgreSQL apply/re-apply validation of migration 140 with structural and trigger behavior postconditions;
- confirmation of the approved transaction/serialization mechanism for the production migration runner;
- separate deployment authorization after successful migration validation.
