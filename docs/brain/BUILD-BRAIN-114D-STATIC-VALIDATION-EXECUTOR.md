# BUILD-BRAIN-114D — Read-only static validation executor

## Objective

Add a safe authoritative validation step between autonomous workspace mutation and any future executable test/commit capability. The validator must produce evidence without importing or executing repository code and without invoking subprocesses, shells, network services, or credentials.

## Dependency

This slice is stacked on BUILD-BRAIN-114C, which is stacked on BUILD-BRAIN-114B. It reuses the same immutable repository identity, Git checkout identity, isolated-workspace marker, and allowlisted engineering path boundary.

## Implemented

- Added autonomous role `isolated_workspace_static_validator`.
- Requires the exact disposable isolation marker for the requested repository and `autonomy/*` branch.
- Accepts only explicit file paths and expected SHA-256 post-patch hashes.
- Restricts validation to the same initial engineering surface as BUILD-BRAIN-114C: `app/`, `tests/`, and `docs/brain/`.
- Rejects traversal, protected paths, duplicate targets, invalid digests, excessive file counts, oversized files, aggregate byte overflow, missing files, symlinks/path escapes inherited from the repository reader, branch mismatch, and mutation intent.
- Validates UTF-8 for every target.
- For Python files, parses with `ast.parse` and compiles the AST object with Python's built-in `compile` function. This checks syntax/compile semantics without importing or executing the changed module and without writing bytecode.
- Non-Python text receives deterministic hash + UTF-8 validation with syntax marked not applicable.
- Rechecks checkout identity after the scan.
- Emits a deterministic authoritative receipt containing the immutable starting Git commit, target hashes, byte counts, language/syntax states, and explicit negative authority claims: repository code not imported/executed, no subprocess, no shell, no network, no files written.
- Executor registry now exposes `repository_code_execution` independently from workspace mutation and external side effects.

## What this does not validate

Static validation is intentionally narrower than CI. It does not prove:

- Ruff/lint success;
- unit/integration test success;
- dependency compatibility;
- runtime route mounting;
- database behavior;
- browser behavior;
- network integration;
- packaging/build success.

Those require a future sandboxed executable validation layer. Until such a sandbox exists and is independently validated, static validation receipts must not be treated as equivalent to successful CI.

## Validation coverage

Focused tests cover:

- hash-bound Python syntax validation;
- invalid Python rejection;
- stale post-patch hash rejection;
- UTF-8/hash validation for Brain documentation;
- path escape/protected-path/duplicate rejection;
- branch, marker, and non-mutating guards;
- registry classification as authoritative but non-mutating and non-executing.

Dedicated workflow: `.github/workflows/build-brain-114d.yml`.

Backend GitHub-hosted runner incident #533 remains active at implementation time. Zero-step workflow failures are recorded as infrastructure failures and are not represented as executable validation success or code failure.

## Autonomy significance

With BUILD-BRAIN-114B through 114D stacked, the engineering loop now has three bounded authoritative primitives:

1. inspect repository evidence and bind it to an immutable commit;
2. modify an explicitly disposable isolated worktree using exact preimage hashes;
3. independently verify the resulting file hashes and Python syntax without executing repository code.

The next safe milestone is a sandboxed executable validator capable of running a small fixed test/lint profile with network disabled and no credentials, followed by a separate governed commit/PR proposal layer. Merge and deployment authority remain outside the autonomous boundary.
