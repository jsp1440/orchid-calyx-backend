# CALYX-LIVE-GRAPH-OPERATOR-002 — Reusable domain-selectable live staging operator

## Context

CALYX-LIVE-GRAPH-DRY-RUN-001 proved the deployed Render service is ready for persistent resumable staging and completed the first live occurrences dry run with zero validation problems and zero second-pass delta. The initial operator always selected the first preferred ready domain and could not safely resume a known session, which required temporary diagnostic workflow code for the second pass.

## Implementation

`scripts/run_bounded_resumable_graph_dry_run.py` is upgraded while preserving its staging-only boundary.

New operator controls:

- `CALYX_BOUNDED_DRY_RUN_DOMAIN` — optional explicit domain; must be present in the live `ready_domains` inventory or the operator fails closed;
- `CALYX_BOUNDED_DRY_RUN_RUN_ID` — optional existing single-domain dry-run ID; when present, the operator resumes that exact session once instead of creating a new session.

Every invocation now:

1. authenticates through the owner session-token endpoint;
2. fetches `/api/platform/knowledge-graph/deployment-preflight`;
3. requires `ready_for_live_resumable_dry_run=true`;
4. requires every inspected staging response to explicitly state `production_graph_mutation=false`;
5. performs at most one staging resume step;
6. emits versioned evidence including action, domain, deployed commit, preflight contract, before/report state, and governance flags;
7. never invokes a publication or taxonomy-activation endpoint.

## Retry policy

The live run exposed a transient HTTP 502 during owner-session authentication. The operator therefore permits a small bounded retry only for authentication and read-only GET operations such as deployment preflight, inventory, and status retrieval.

It deliberately does **not** retry dry-run creation or resume POSTs. An HTTP response can be lost after the server has checkpointed a staging step, so automatically replaying those operations could advance work twice.

## Bounds

- one domain per run;
- batch size 100;
- `max_batches_per_step=1`;
- one start/resume staging step per invocation;
- no production Knowledge Graph mutation;
- no automatic publication;
- no taxonomy activation.

## Validation gate

Required before merge:

- focused operator tests;
- compile and diff hygiene through `CALYX Bounded Live Dry Run` PR validation;
- BUILD-088E regression validation;
- workflow-governance audit;
- unchanged-head review-thread check.

## Governance

This operator improves repeatability of staging validation only. A completed dry run may report `publication_authorization_ready=true`, but the operator has no publication call and that flag does not constitute owner approval to mutate the production Knowledge Graph.
