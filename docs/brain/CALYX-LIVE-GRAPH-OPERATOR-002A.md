# CALYX-LIVE-GRAPH-OPERATOR-002A — Deployment preflight v3 contract correction

## Incident

The reusable bounded live Knowledge Graph operator merged in CALYX-LIVE-GRAPH-OPERATOR-002 correctly required an explicit no-mutation assertion before staging, but it reused the dry-run response field `production_graph_mutation` for the deployment preflight response.

The authoritative `calyx-graph-deployment-preflight-v3` contract instead exposes:

- `graph_mutation: false`;
- `filesystem_mutation: false`;
- `ready_for_live_resumable_dry_run`;
- `blockers`.

The mismatch was discovered during a bounded literature diagnostic. The operator failed closed at deployment preflight with `production_graph_mutation_not_explicitly_false` before creating or resuming any literature dry-run session. No staging state changed.

## Correction

The operator now validates the exact preflight contract and requires:

1. `contract == calyx-graph-deployment-preflight-v3`;
2. `graph_mutation is false`;
3. `filesystem_mutation is false`;
4. `ready_for_live_resumable_dry_run is true`.

Actual dry-run start, resume, status, and report responses continue to require `production_graph_mutation is false`.

The distinction is intentional: deployment preflight describes mutation capability of the preflight itself, while dry-run responses describe whether the Knowledge Graph staging operation can mutate production graph state.

## Regression coverage

Focused tests now use the actual deployed v3 schema and reject:

- contract mismatch;
- missing or true `graph_mutation`;
- missing or true `filesystem_mutation`;
- not-ready preflight responses with blockers.

Existing tests continue to verify that dry-run responses fail closed when `production_graph_mutation` is missing and that an existing session is resumed at most once per invocation.

## Governance

The correction grants no additional authority. The operator still contains no publication or taxonomy-activation endpoint call, never automatically retries staging POSTs, and performs at most one bounded staging step per invocation.
