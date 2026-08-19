# CALYX-HARVEST-007 — Production Runtime Repair

Status: implemented on `main`

## Incident

Render production logs on 2026-08-14 showed that biodiversity harvesting was functioning while the newly guaranteed literature lane failed before indexing with:

`psycopg.errors.UndefinedTable: relation "oc_candidate_knowledge.runtime_repository_snapshots" does not exist`

The semantic-index code was deployed, but the shared BUILD-086 durable runtime snapshot table had not been provisioned in the deployment database. This caused `PostgresIndexRepository` initialization to fail and surfaced as `SEMANTIC_INDEX_DATABASE_UNAVAILABLE`.

The same logs confirmed that lane isolation worked correctly: literature failure did not stop iNaturalist or GBIF harvesting, and the API continued serving health checks.

## Repair

`app/persistence/state_repository.py` now performs a narrowly scoped additive bootstrap only when the shared runtime snapshot table is wholly absent. The bootstrap creates:

- `oc_candidate_knowledge.runtime_repository_snapshots`
- the allowed repository kinds `candidate_knowledge`, `evidence_aggregation`, and `semantic_index`
- `oc_candidate_knowledge.runtime_repository_audit`
- the runtime audit index, function, and trigger

The bootstrap does not rewrite or drop constraints on an existing table. Established databases with an older schema continue to require the explicit migration path. This prevents the runtime repair from becoming a general implicit migration engine.

The repair is intended to let literature indexing become durable immediately on a deployment that has the application code but never received the base BUILD-086 runtime table.

## GBIF deployment resilience

Production logs also showed GBIF cycles being interrupted by Render deployments after several minutes of work. The global GBIF harvester previously saved its cursor only at the end of a whole cycle, so a deploy could cause the next process to replay multiple already-processed pages.

`harvesters/gbif_global_api.py` now checkpoints after every successfully persisted page. The adaptive worker also limits each in-process GBIF pass to 120 seconds on the shared web service. This preserves forward progress across deployments and keeps the API-hosted worker bounded.

## Unresolved governed migration

The production warning:

`relation "oc_admin.harvest_safety_state" does not exist`

remains separate. The repository migration `migrations/BUILD-105-harvester-safety.sql` explicitly states `Generated only; do not execute automatically.` The runtime repair therefore does not bypass that governance instruction. Harvesting continues, but durable BUILD-105 safety snapshots and dead-letter persistence remain unavailable until that migration is applied through an authorized database migration path.

## Validation

Focused regression tests were added for:

- additive runtime snapshot bootstrap when the table is missing
- no schema rewrite when the runtime snapshot table already exists
- GBIF page-level checkpoint durability

Existing CI and certification workflows are allowed to complete before additional expansion.

## Production acceptance criteria

After the repaired `main` deploys, the next literature cycle should no longer emit `SEMANTIC_INDEX_DATABASE_UNAVAILABLE`. Expected evidence is a literature log reporting `discovered`, `indexed`, and provider status, followed by normal interaction and biodiversity lanes.

GBIF logs should include an explicit `checkpoint=<offset>` after each successful page. A Render deployment during a GBIF run should resume from the last saved page rather than from the cycle's starting offset.
