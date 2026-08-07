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

### 2026-08-07 runner recovery and corrective validation

The earlier repository-wide zero-step Actions condition is no longer blocking validation. GitHub account billing inspection showed the Actions product budget at `$0` with **Stop usage when budget limit is reached** enabled. The owner raised the Actions budget to `$25/month` while retaining the hard stop and threshold alerts. Hosted jobs then began instantiating real runner steps again.

Once real CI resumed, ordinary code-quality findings were exposed and fixed before further expansion:

- 114E corrected non-object persisted JSON to raise `TypeError` and fixed two Ruff B018 test expressions.
- 114B normalized imports, tuple construction, packed-ref prefix checks, and focused test imports.
- 114C normalized executor import ordering and evidence URI construction.
- 114D normalized executor imports and evidence URI construction.
- Corrected 114B/114C/114D implementations were synchronized into the 114E integration head so broad orchestrator validation sees the same code as focused validation.

Authoritative successful runs obtained during recovery include:

- BUILD-BRAIN-114E run `31209622678`: compile, Ruff, focused integration tests, migration compatibility, and diff hygiene passed.
- BUILD-BRAIN-114C run `31209801405`: passed.
- BUILD-BRAIN-114D run `31209921587`: passed.
- BUILD-BRAIN-114A and BUILD-BRAIN-108-113A also passed on the integration lineage during recovery.

### Final synchronized head

Current validated head: `b58808adef3ca66c0447de7977ee6ec929fac921`.

All triggered validation workflows completed successfully on this same synchronized head:

- BUILD-BRAIN-114B Validation — run `31210354402`
- BUILD-BRAIN-114C Validation — run `31210354423`
- BUILD-BRAIN-114D Validation — run `31210355616`
- BUILD-BRAIN-114E Validation — run `31210354755`
- BUILD-BRAIN-114A Validation — run `31210354411`
- BUILD-BRAIN-108-113A Validation — run `31210355015`
- CALYX-AGENT-003 Validation — run `31210354468`

This establishes one coherent, executable CI-green autonomous-engineering integration head after runner recovery and ancestor synchronization. Merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain unauthorized.

## Next milestone

First reconcile this now-validated autonomy surface with current `main` without overwriting newer mainline work. A clean consolidation branch, `feature/brain-114f-current-main-consolidation`, has been created from current `main` for that purpose. After that consolidation is green, the next safe autonomy milestone is a sandboxed executable validation adapter with a fixed command profile, network isolation, no credentials, output/time/resource ceilings, and explicit repository-code-execution receipts. Only after that validator is proven should Calyx gain a separate governed commit/PR-proposal capability. Merge and deployment authority remain human-governed.
