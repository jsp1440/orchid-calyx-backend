# CALYX-LIVE-GRAPH-DRY-RUN-001 — First completed production-staging Knowledge Graph dry run

## Scope

This record captures the first owner-authenticated live resumable Knowledge Graph dry run executed against the deployed Calyx backend after the deployment preflight became green. The work remained staging-only. No production Knowledge Graph publication endpoint was invoked.

## Deployment preflight

Temporary diagnostic PR #575 executed the existing read-only deployment preflight from GitHub-hosted infrastructure using protected repository configuration.

Workflow run: `31225245035`

Observed deployed service state:

- backend: `https://orchid-calyx-backend.onrender.com`;
- deployed commit reported by the service: `cafe087f75189c62689cef42c30b84d52a1d2fc2`;
- database reachable: true;
- required Knowledge Graph and Candidate Knowledge routes mounted: true;
- blockers: none;
- persistent mount: `/var/data`;
- dry-run staging directory: `/var/data/calyx-graph-dry-runs`;
- staging directory exists, is inside the persistent mount, and is writable;
- `ready_for_live_resumable_dry_run`: true;
- `graph_mutation`: false;
- Reasoning Center Candidate Knowledge handoff mounted: true;
- automatic publication: false;
- human review required: true.

Preflight evidence artifact: `9011852633`, digest `sha256:0a47ad8b85293a031c8d2966f29fb4a9d30dae2a8c4557ee771b5b9b0763185e`.

## First bounded staging pass

Temporary diagnostic PR #577 executed the existing bounded operator against the live backend.

Workflow run: `31225465102`

Bounds:

- one domain;
- batch size 100;
- maximum one batch per step;
- no publication endpoint;
- no production graph mutation.

Selected domain: `occurrences`.

Created live dry-run session:

`ec96f45e-b6c4-4214-92e1-3c56c72d5c61`

First pass results:

- source rows observed: 26;
- occurrence nodes staged: 26;
- occurrence edges staged: 26;
- taxonomy seed nodes: 20;
- total staging nodes: 46;
- total staging edges: 26;
- invalid rows: 0;
- duplicate edges: 0;
- orphan nodes: 0;
- orphan edges: 0;
- missing provenance: 0;
- invalid canonical keys: 0;
- vocabulary violations: 0;
- total validation problems: 0;
- validation healthy: true.

The first bounded step stopped at pass 2 with `next_action=resume`. Production graph mutation and publication remained false.

Initial evidence artifact: `9011929500`, digest `sha256:9da8077d56298fe65d8098b734b4b4d85ffbcdc6595a0654bbb34dae0417d5f6`.

## Idempotency completion

A second bounded attempt initially received HTTP 502 during owner-session authentication. No dry-run resume request had been sent, so staging state was unchanged. The exact failed job was retried once without modifying code.

The retry successfully resumed the same run exactly once and completed the second pass.

Final state:

- session status: `completed`;
- domain status: `completed`;
- domains completed: 1 / 1;
- domain completion: 100%;
- batches completed: 2;
- second-pass nodes: 0;
- second-pass edges: 0;
- `zero_delta`: true;
- blockers: none;
- total validation problems: 0;
- validation healthy: true;
- production graph mutation: false;
- publication endpoint invoked: false;
- next action: `review`;
- `publication_authorization_ready`: true.

Final resume evidence artifact: `9011998250`, digest `sha256:132ff33310f277249d62f4cfb787cd5fa05c9b3d4ee2083a45208630a4c4602d`.

## Governance boundary

`publication_authorization_ready=true` means the staging dry run satisfied the software's dry-run publication-input gate. It does **not** constitute owner authorization to publish or mutate the production Knowledge Graph.

No production publication, taxonomy activation, deployment change, credential disclosure, automatic merge authority, or production Knowledge Graph mutation was performed as part of this run.

The next safe technical step is to repeat bounded dry-run validation for the remaining ready scientific domains and/or create a consolidated multi-domain staging run. Any transition from validated staging into production Knowledge Graph publication remains an explicit governance decision.
