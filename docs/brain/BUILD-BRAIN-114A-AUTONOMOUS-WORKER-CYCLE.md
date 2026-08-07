# BUILD-BRAIN-114A — Autonomous deterministic program worker cycle

## Objective

Remove the manual claim/execute bottleneck for started Calyx engineering programs without expanding authority beyond the deterministic internal executor.

## Implemented

- Added `run_deterministic_program_cycle`, an owner-scoped bounded worker cycle.
- The cycle repeatedly claims the next persisted runnable job, executes it through `DeterministicDryRunExecutor`, verifies and persists its receipt, releases downstream dependencies, and continues until idle or the configured job budget is exhausted.
- The cycle reuses the existing persisted scheduler, admission policy, durable leases, lease atomicity protections, governed assignment factory, receipt bridge, and program repository.
- Added protected `POST /brain/orchestrator/programs/workers/run-cycle` for an authenticated owner to execute a bounded cycle without individual claim and execute calls.
- Added `ProgramAutonomyPolicy`, which fails closed unless continuous mode is explicitly enabled and an owner is configured.
- Added `runtime.program_autonomy_worker`, supporting one-cycle execution or a continuous polling process.
- Mission Control portfolio output now reports the continuous worker policy, authorization state, automatic-claim state, automatic-execution state, cycle budget, and safety boundaries.
- Added `.github/workflows/calyx-program-autonomy.yml`, scheduled every 15 minutes. It performs no database work unless the repository autonomy flag, owner, and a production database connection are configured.
- Added focused CI and regression coverage.

## Scheduled runner configuration

Repository variables:

- `CALYX_PROGRAM_AUTONOMY_ENABLED=true`
- `CALYX_PROGRAM_AUTONOMY_OWNER=<authenticated Calyx owner subject>`
- optional `CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE` (default `10`)

Database connection must be supplied through existing repository secrets using either `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`/`PGPORT` or `DATABASE_URL`.

When any required gate is absent, the scheduled workflow exits successfully without touching the database.

## Continuous service entrypoint

A persistent worker service can run:

`python -m runtime.program_autonomy_worker`

It requires the same environment policy. Continuous service deployment is independent of the scheduled GitHub runner; both use the same cycle semantics and concurrency-safe database leases.

## Operational chain

`started program -> persisted scheduler -> automatic owner-scoped claim -> governed assignment -> deterministic dry run -> verified receipt -> atomic lease completion -> downstream dependency release -> next claim`

No human claim or per-job execute action is required inside this chain.

## Failure behavior

- Idle queue: exits the cycle cleanly.
- Job budget reached: stops with `budget_exhausted`; released downstream work remains queued for the next cycle.
- Missing owner or disabled policy: no continuous work runs.
- Missing database secret in the scheduled workflow: no database work runs.
- Execution exception: the cycle stops and reports the job identity and error. Existing lease recovery/retry behavior remains authoritative.
- Cross-owner programs are never claimed by an owner-scoped cycle.

## Governance

This build does **not** authorize:

- shell execution;
- external provider execution;
- GitHub code writes;
- pull-request creation or merge;
- deployment;
- scientific publication;
- taxonomy activation;
- credential access by an executor;
- production Knowledge Graph mutation.

A program must already be explicitly started before its jobs are eligible for automatic deterministic execution. Scientific release and consequential engineering actions remain separately governed.

## Next integration

The next autonomy step is to register reviewed executable adapters beyond the deterministic reference executor, beginning with evidence-producing read-only capabilities. Each adapter must declare its authority, inputs, outputs, side effects, idempotency key, receipt schema, timeout behavior, and governance class before the worker registry can invoke it.
