# BUILD-BRAIN-114R-R2 — strengthened authorization-bound execution plan

## Objective

Rebuild BUILD-BRAIN-114R directly on the strengthened 114M-R1 → 114N-R2 → 114P-R2 → 114O-R2 → 114Q-R2 trust chain, rather than continuing the historical 114R ancestry.

## Trust lineage

The planner consumes the exact manifest-v2, durable `patch_program_job_id`, persisted dual-review evidence, owner authorization request, and externally verified Ed25519 owner grant from the R2 parent chain. The regression fixture computes the isolated patch execution receipt input checksum from `assignment_inputs_for_program_job(program, claimed)`, matching the strengthened runtime trust root rather than using a placeholder checksum.

## Plan contract

The deterministic `calyx-git-proposal-execution-plan-v2` binds:

- exact manifest digest;
- durable patch program-job identity;
- authorization-request digest;
- repository and exact base commit;
- proposal branch;
- changed-file postimage hashes;
- validation receipt digests;
- durable review authorization digests;
- externally verified owner identity, expiry, and signature-envelope digest;
- commit title, PR title, and summary;
- dependency-closed ordered proposal operations.

Allowed planning operations are limited to a dependency-closed prefix of `create_branch → create_commit → push_branch → open_pull_request`. The planner canonicalizes operation order and rejects sparse prerequisite-violating action sets.

## Authority boundary

This slice is plan-only. It performs no Git or GitHub mutation and contains no shell, subprocess, HTTP, GitHub API, credential loading, merge, auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation capability.

## Validation

Focused regressions cover deterministic planning, exact durable patch identity, canonical assignment-input checksum provenance, dependency closure, manifest/request tampering, invalid owner signatures, and expiration. A dedicated read-only CI workflow compiles, lints, formats, runs the focused 114R/114Q/114O regressions, checks authority markers, and runs diff hygiene.

Canonical private-repository hosted-runner incident #481 currently prevents executable CI from materializing steps. Keep this slice draft until an exact-head job obtains a runner and completes the validation suite.

## Next dependency

Only after this exact R2 planner is executable-CI validated should BUILD-BRAIN-114S be rebuilt on this branch. 114T durability/recovery remains downstream of validated 114S-R2.
