# BUILD-BRAIN-114C — Bounded isolated-workspace patch executor

## Objective

Give the autonomous engine a narrowly governed file-mutation capability without granting shell, Git, network, credential, merge, deployment, publication, taxonomy, or production scientific authority.

## Current-main implementation

- Adds authoritative role `isolated_workspace_patcher`.
- Operates only in a pre-created disposable worktree carrying `.calyx-isolated-workspace.json` bound to the repository and an `autonomy/*` branch.
- Requires the explicit `workspace_write` capability and `mutating_intent=true`.
- Restricts writes to `app/`, `tests/`, and `docs/brain/`.
- Limits each job to eight files, 500 KB per file, and 1.5 MB total output.
- Requires exact SHA-256 preimage binding for replacement or explicit `absent` state for creation.
- Validates every patch before the first write, so a stale input in a multi-file patch cannot partially mutate earlier files.
- Uses same-directory staged files, fsync, atomic replace, and rollback of already-applied replacements on a later replacement failure.
- Reuses BUILD-BRAIN-114B checkout identity and descriptor-safe read primitives and rechecks checkout identity after mutation.
- Produces deterministic authoritative receipts with before/after hashes, file sizes, and explicit `commit_created=false` and `validation_commands_run=false`.
- `AuthoritativeExecutorRegistry` exposes workspace mutation separately from external side effects and repository-code execution.
- Autonomous-cycle projections now report whether workspace mutation or repository-code execution occurred.

## Governance boundaries

This build does not create or switch Git branches, invoke Git commands, execute repository code, run tests, install dependencies, use shell/subprocess, access the network or credentials, create commits or pull requests, merge, deploy, publish, activate taxonomy, modify a production database, or mutate the production Knowledge Graph.

The marker file is a local disposable-workspace authorization boundary, not permission to mutate the authoritative repository checkout.

## Validation

Focused validation compiles and lints the patch executor, registry, cycle projection, and focused tests; it also runs the isolated-patch, repository-evidence, autonomous-cycle, and dry-run regressions plus diff hygiene.

This clean current-main slice supersedes the stale stacked BUILD-BRAIN-114C PR #538 after BUILD-BRAIN-114B was merged under a replacement current-main SHA.
