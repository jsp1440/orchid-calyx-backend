# BUILD-BRAIN-114A — Autonomous authoritative program worker cycle

## Objective

Remove the manual claim/execute bottleneck for started Calyx engineering programs without allowing dry runs or unregistered roles to masquerade as completed work.

## Implemented

- Added `run_deterministic_program_cycle`, an owner-scoped bounded worker cycle.
- The cycle uses the persisted scheduler and durable lease machinery, but claims only roles explicitly registered in `AuthoritativeExecutorRegistry`.
- Added the narrowly scoped `autonomy_probe` role and `autonomy_probe_v1` executor. It is authoritative only for non-mutating internal orchestration probes and has no external side effects.
- Ordinary engineering roles such as Brain, Knowledge Graph, Atlas, Conservatory, literature, Vision, and operations roles are not automatically claimable until a reviewed authoritative adapter is registered for them.
- Corrected deterministic dry-run semantics: `DeterministicDryRunExecutor` is preflight-only. A successful dry run returns a non-authoritative receipt, releases its lease, restores the job to `queued`, records no terminal outcome, stores no authoritative evidence, and does not consume an execution attempt.
- The dry-run HTTP contract reports `released_job`, `authoritative: false`, and `mode: deterministic_dry_run_preflight`; it no longer represents the result as a completed job.
- The authoritative receipt bridge remains reserved for registered authoritative executor receipts.
- Added protected `POST /brain/orchestrator/programs/workers/run-cycle` for an authenticated owner to run a bounded authoritative cycle.
- Added `ProgramAutonomyPolicy`, which fails closed unless continuous mode is explicitly enabled and an owner is configured. Explicit empty environment mappings remain empty and never inherit ambient autonomy variables.
- Added `runtime.program_autonomy_worker`, supporting one-cycle execution or a continuous polling process.
- Mission Control portfolio output reports continuous-worker policy, authorization state, automatic-claim state, automatic-execution state, cycle budget, and governance boundaries.
- Added `.github/workflows/calyx-program-autonomy.yml`, scheduled every 15 minutes. It performs no database work unless the repository autonomy flag, owner, and a database connection are configured.
- Expanded focused CI to cover the registry, worker, dry-run service, receipt bridge, scheduler, Mission Control portfolio, and both authoritative and non-authoritative execution paths.

## Scheduled runner configuration

Repository variables:

- `CALYX_PROGRAM_AUTONOMY_ENABLED=true`
- `CALYX_PROGRAM_AUTONOMY_OWNER=<authenticated Calyx owner subject>`
- optional `CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE` (default `10`)

Database connection must be supplied through existing repository secrets using either `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`/`PGPORT` or `DATABASE_URL`.

When any required gate is absent, the scheduled workflow exits successfully without touching the database.

## Operational chain

For an explicitly registered authoritative role:

`started program -> persisted scheduler -> owner-scoped role-filtered claim -> governed assignment -> registered authoritative executor -> verified receipt -> atomic lease completion -> downstream dependency release -> next claim`

For a dry run:

`claimed job -> governed assignment -> deterministic preflight -> non-authoritative receipt -> lease release -> job returns to queued with no outcome`

## Failure and safety behavior

- Idle eligible queue: exits the cycle cleanly.
- Job budget reached: stops with `budget_exhausted`; released downstream eligible work remains queued for the next cycle.
- Missing owner or disabled policy: no continuous work runs.
- Missing database secret in the scheduled workflow: no database work runs.
- Execution exception: the cycle stops and reports the job identity and error; existing lease recovery/retry behavior remains authoritative.
- Cross-owner programs are never claimed by an owner-scoped cycle.
- Unregistered role: the autonomous cycle does not claim it and cannot complete it.
- Dry run: never creates `DELIVERED`, `BLOCKED`, or any other authoritative program outcome.

## Governance

This build does **not** authorize:

- shell execution;
- external provider execution;
- GitHub code writes by an executor;
- pull-request creation or merge;
- deployment;
- scientific publication;
- taxonomy activation;
- credential access by an executor;
- production Knowledge Graph mutation.

A program must already be explicitly started before its jobs are eligible. Being started is necessary but not sufficient: the job role must also have an explicitly registered authoritative adapter. Scientific release and consequential engineering actions remain separately governed.

## Review correction

Final review identified that the earlier implementation allowed a dry-run `DELIVERED` receipt to become an authoritative program completion. That design was rejected. The corrected architecture separates preflight receipts from authoritative executor receipts and adds role-level executor admission before an autonomous claim can occur.

## Next integration

The next autonomy step is to register the first genuinely useful evidence-producing read-only adapter. Each adapter must declare its authority, inputs, outputs, side effects, idempotency key, receipt schema, timeout behavior, and governance class before the worker registry can invoke it. No adapter should be registered merely to increase apparent autonomy coverage.
