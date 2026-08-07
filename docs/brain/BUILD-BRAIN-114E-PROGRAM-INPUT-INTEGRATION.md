# BUILD-BRAIN-114E — Persisted job inputs and patch→static-validation integration

## Objective

Close the integration gap between the bounded BUILD-BRAIN-114C/114D executors and the persistent autonomous engineering program cycle. Before this slice, those executors existed as authoritative adapters but the persistent program model could not carry the patch or validation manifests they require, and the assignment factory could not grant the isolated patch role its `workspace_write` capability.

## Implemented

- Added nullable `input_json` persistence to `calyx_engineering_program_jobs` and a compatible `ADD COLUMN IF NOT EXISTS` migration path.
- Added bounded per-job `inputs` to `ProgramJobSpec`.
- Inputs are canonical JSON only, have non-empty string keys, are capped at 2 MB, and are incorporated into the deterministic work fingerprint.
- Program creation persists the canonical input manifest before scheduling.
- Program snapshots do not echo input contents. They expose only manifest presence, SHA-256, and top-level keys.
- Governed assignment construction parses persisted input JSON, rejects non-object payloads and reserved-field overrides, and projects allowed manifest keys into the executor job payload.
- Reserved identity/governance fields such as repository, branch, role, mutating intent, job key, and attempt count cannot be replaced by persisted inputs.
- The isolated patch role alone receives the additional `workspace_write` requested capability.
- Read-only repository evidence, static validation, and existing probe roles retain the safe capability set.
- Assignment governance now truthfully reports bounded authoritative-adapter mode and whether workspace write is authorized.
- Program API job requests now accept a governed `inputs` object; repository-level canonicalization and byte ceilings remain authoritative.
- The autonomous cycle now catches malformed typed executor input (`TypeError`) and returns a governed error result instead of escaping the cycle.

## End-to-end integration proof encoded in tests

`tests/test_calyx_autonomous_patch_validation_program.py` constructs an isolated fake Git worktree and a durable two-job program:

1. `isolated_workspace_patcher` changes one Python file using an exact preimage SHA-256.
2. `isolated_workspace_static_validator` depends on the patch job and verifies the exact post-patch SHA-256 plus Python syntax.

The test drives the ordinary `run_deterministic_program_cycle` path with the real authoritative executor registry, worker claim/lease flow, assignment factory, execution receipts, completion bridge, dependency release, and persistent program status. Expected result: both jobs are delivered, the file changes exactly once, static validation performs no repository code execution, and the program reaches `completed` while merge/deploy/publication remain false.

Additional tests verify input-manifest redaction, input-sensitive work fingerprints, canonical JSON requirements, and size ceilings.

## Authority boundary

This slice does not add shell, subprocess, network, credentials, Git commit, PR creation, merge, deploy, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

The current autonomous engineering chain can therefore:

- claim governed work;
- inspect repository evidence;
- carry deterministic work inputs durably;
- mutate explicitly isolated disposable workspaces on exact preimages;
- statically validate exact resulting files;
- persist authoritative receipts and release downstream dependencies.

It still cannot run executable tests/lint in a sandbox, create a Git commit, open a PR from inside Calyx, merge, deploy, or publish.

## Validation

Dedicated workflow: `.github/workflows/build-brain-114e.yml`.

The workflow compiles and lints the changed integration surface, runs the end-to-end patch→validate program test plus the prior 114B/114C/114D and assignment/cycle regressions, checks migration compatibility, and runs diff hygiene.

Backend GitHub-hosted runner incident #533 remains active at implementation time. Any workflow result with zero instantiated steps is infrastructure evidence only and must not be represented as executable code validation.

## Next milestone

The next safe autonomy milestone is a sandboxed executable validation adapter with a fixed command profile, network isolation, no credentials, output/time/resource ceilings, and explicit repository-code-execution receipts. Only after that validator is proven should Calyx gain a separate governed commit/PR-proposal capability. Merge and deployment authority remain human-governed.
