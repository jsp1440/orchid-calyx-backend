# BUILD-BRAIN-111A — Persisted scheduler and Mission Control integration

## Objective

Connect the deterministic dependency scheduler to durable `CalyxProgramJob` and `CalyxProgramDependency` rows so worker admission and Mission Control use the same authoritative scheduling projection.

## Implemented

- Namespaced persisted job identities as `program_id:job_key` to avoid cross-program collisions.
- Adapted durable job status, outcome, role, repository, branch mutation state, creation order, and dependency rows into the pure scheduler.
- Added per-program concurrency limits using each program's `max_active_jobs` value.
- Preserved global, role, repository, and one-mutator-per-branch capacity limits.
- Added fail-closed handling for unsupported persisted states, missing dependency jobs, and cross-program dependency mismatches.
- Changed `PersistentProgramWorker.claim()` to accept only jobs admitted by the persisted scheduler and to follow deterministic runnable rank.
- Added stable persisted ordering by creation time, program identity, and job key rather than random UUID ordering.
- Added the same persisted schedule to the existing owner-protected Mission Control operational-status payload.
- Added regression coverage for duplicate job keys across programs, per-program capacity, critical-path worker ordering, and Mission Control/worker agreement.

## Validation correction

The first focused run exposed a real mismatch: a same-branch mutator rejected by the legacy admission policy had already consumed a provisional repository slot in the scheduler. The branch mutation rule was moved into the deterministic scheduler, preventing rejected candidates from consuming capacity and restoring agreement between schedule projection and worker admission.

The final owner-authored synchronization commit includes the deterministic persisted-ordering improvement and triggers validation of the exact merge candidate without an automation-origin approval gate.

## Governance

- The scheduler projection is read-only.
- Worker claims remain atomic and lease-backed.
- Existing engineering admission policy remains a secondary safety gate.
- Production activation remains false.
- No deployment, publication, credential access, or production Knowledge Graph mutation is authorized.

## Operational result

The Brain now has one shared scheduling truth:

`persisted jobs and dependencies -> deterministic scheduler -> Mission Control snapshot + atomic worker claim`

A worker cannot claim a queued job that the scheduler reports as blocked by dependencies, branch safety, or capacity.

## Next bounded integration

Add protected schedule filtering and exact remediation summaries to the broader Mission Control portfolio API, then connect reviewed scheduler decisions to governed assignment creation without enabling external execution or automatic publication.
