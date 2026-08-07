# BUILD-BRAIN-114B — Read-only repository evidence executor

## Objective

Add the first genuinely useful authoritative autonomous adapter while preserving the no-shell, no-network, no-credential boundary.

## Current-main implementation

- Adds the `repository_evidence_reader` autonomous role.
- Reads only a fixed allowlist of engineering-control files from an explicitly configured local checkout.
- Records path, byte size, required/optional status, and SHA-256 hashes; file contents are never included in receipts.
- Binds evidence to repository, requested branch, actual checkout branch, and immutable 40-character commit SHA.
- Re-checks checkout identity after collection and fails closed if branch or commit changed during the scan.
- Labels provenance as `local_worktree_observation`; commit SHA is checkout context, not a claim that bytes were reconstructed from Git objects.
- Uses descriptor-relative no-follow traversal, `fstat` validation, regular-file checks, per-file and aggregate byte bounds, and UTF-8 validation.
- Rejects path traversal, symlink escape, non-regular files, invalid Git metadata, repository mismatch, revision mismatch, detached branch requests, checkout changes, and mutating intent.
- Registers the adapter in `AuthoritativeExecutorRegistry`; it is authoritative only for read-only repository evidence collection and has no external side effects.

## Execution chain

`started program -> scheduler -> role-filtered claim -> governed assignment -> verified checkout revision -> descriptor-safe evidence read -> stable-revision recheck -> hash-only receipt -> atomic completion -> dependency release`

## Review corrections

Three provenance/safety defects were corrected before merge consideration:

1. requested branch/revision was not originally verified;
2. check-then-read file access left a TOCTOU/symlink window;
3. checkout identity was initially checked only before evidence collection.

All three now fail closed and are covered by focused regression tests.

## Validation contract

`scripts/validate_repository_evidence_executor.py` is the single portable validation entry point. It inventories required files, compiles the changed surface, runs Ruff, runs the focused executor/autonomy regressions, and writes `artifacts/validation/repository-evidence-executor.json` with exact commands, timestamps, return codes, environment information, failure stage, and explicit no-merge/no-deploy/no-publication/no-production-write authority.

GitHub-hosted runners are currently tracked under issue #533 because jobs are failing before any step is instantiated (`steps=null`). This build must remain unmerged until a real runner executes the validator successfully.

## Governance

No shell execution, external network access, GitHub API use by the executor, credentials, repository writes, merge, deployment, publication, taxonomy activation, or production scientific-data mutation is authorized by this build.
