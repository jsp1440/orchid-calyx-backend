# BUILD-BRAIN-114C — Bounded isolated-workspace patch executor

## Objective

Advance Calyx from read-only authoritative repository inspection to the first bounded authoritative engineering mutation capability without granting shell, network, credential, commit, merge, deploy, publication, taxonomy-activation, or production scientific-write authority.

## Dependency

This slice is stacked on BUILD-BRAIN-114B / PR #527 and depends on its read-only repository identity and filesystem-safety primitives.

## Implemented

- Added autonomous role `isolated_workspace_patcher`.
- Added `IsolatedWorkspacePatchExecutor`.
- The executor operates only inside a pre-created local workspace whose Git branch begins with `autonomy/`.
- The workspace must contain `.calyx-isolated-workspace.json` with exact repository/branch identity plus `disposable: true` and `workspace_write_authorized: true`.
- The marker cannot be created by this executor because the repository root is outside the mutation allowlist.
- Initial mutation allowlist is intentionally narrow: `app/`, `tests/`, and `docs/brain/`.
- `.git`, workflow definitions, credentials, arbitrary configuration, deployment files, and paths outside the workspace are not writable.
- Each requested replacement is bound to an exact SHA-256 preimage. New files require the explicit `absent` preimage state.
- Duplicate paths, stale preimages, invalid hashes, non-UTF-8 existing files, oversized payloads, excessive file counts, missing parent directories, path escapes, and symlink targets fail closed.
- Every patch in a multi-file request is fully validated before the first write, preventing partial mutation from validation failures.
- Writes are staged to same-directory temporary files, flushed/fsynced, then atomically replaced per file. Replacement failures trigger best-effort rollback of already-applied files.
- The executor verifies that the Git checkout identity did not change during mutation.
- Delivery receipts contain repository/branch/commit identity, per-file before/after hashes, create/replace state, byte counts, and explicit statements that no commit or validation command was run.
- File contents are not copied into evidence URIs; evidence binds the immutable starting commit and resulting file hashes.
- Executor-registry status now distinguishes `workspace_mutation` from external side effects.

## Authority boundary

This is deliberately not yet a complete autonomous coding loop. BUILD-BRAIN-114C can modify a disposable worktree only after an external trusted mechanism has created and marked that worktree. It cannot:

- create or switch Git branches;
- invoke Git or a shell;
- install dependencies;
- execute tests or linters;
- access network services or credentials;
- create commits or pull requests;
- merge or deploy;
- publish scientific content;
- activate taxonomy releases;
- mutate production databases or the production Knowledge Graph.

The next autonomy layer should add a separately allowlisted validation executor and then a governed handoff that requires successful validation evidence before any proposed repository commit/PR action is considered.

## Validation

Focused tests cover:

- existing-file replacement with receipt verification;
- new-file creation only from explicit absent preimage;
- stale-preimage rejection with no partial multi-file mutation;
- protected-path and traversal rejection;
- branch mismatch and missing isolation marker;
- symlink-target rejection;
- prohibited capability rejection;
- registry visibility of the workspace-mutation boundary.

Dedicated workflow: `.github/workflows/build-brain-114c.yml`.

At implementation time, backend GitHub-hosted runners are affected by issue #533 and may terminate before the first workflow step. A zero-step failure is infrastructure evidence, not executable compile/Ruff/pytest evidence. This PR must remain draft until the focused workflow actually runs its steps successfully.

## Governance result

This slice crosses an important autonomy threshold: Calyx may now be authorized to make deterministic, preimage-bound code/test/Brain-document changes in a disposable isolated worktree, but it still cannot validate, commit, publish, merge, deploy, or touch production scientific state.
