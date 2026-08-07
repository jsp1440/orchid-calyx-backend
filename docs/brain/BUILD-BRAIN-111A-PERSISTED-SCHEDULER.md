# BUILD-BRAIN-111A — Persisted scheduler and Mission Control integration

## Objective

Connect the deterministic dependency scheduler to durable `CalyxProgramJob` and `CalyxProgramDependency` rows so worker admission and Mission Control use the same authoritative scheduling projection.

## Implemented

- Namespaced persisted job identities as `program_id:job_key` to avoid cross-program collisions.
- Adapted durable job status, outcome, role, repository, creation order, and dependency rows into the pure scheduler.
- Added per-program concurrency limits using each program's `max_active_jobs` value.
- Preserved global, role, and repository capacity limits.
- Added fail-closed handling for unsupported persisted states, missing dependency jobs, and cross-program dependency mismatches.
- Changed `PersistentProgramWorker.claim()` to accept only jobs admitted by the persisted scheduler and to follow deterministic runnable rank.
- Added the same persisted schedule to the existing owner-protected Mission Control operational-status payload.
- Added regression coverage for duplicate job keys across programs, per-program capacity, critical-path worker ordering, and Mission Control/worker agreement.

## Governance

- The scheduler projection is read-only.
- Worker claims remain atomic and lease-backed.
- Existing engineering admission policy remains a secondary safety gate.
- Production activation remains false.
- No deployment, publication, credential access, or production Knowledge Graph mutation is authorized.

## Operational result

The Brain now has one shared scheduling truth:

`persisted jobs and dependencies -> deterministic scheduler -> Mission Control snapshot + atomic worker claim`

A worker cannot claim a queued job that the scheduler reports as blocked by dependencies or capacity.

## Next bounded integration

Add protected schedule filtering and exact remediation summaries to the broader Mission Control portfolio API, then connect reviewed scheduler decisions to governed assignment creation without enabling external execution or automatic publication.
