# BUILD-BRAIN-114D — Read-only static validation executor

## Objective

Add a safe authoritative validation step between autonomous workspace mutation and any future executable test/commit capability. The validator produces evidence without importing or executing repository code and without invoking subprocesses, shells, network services, or credentials.

## Current-main integration

This implementation is rebuilt on the current `main` lineage after BUILD-BRAIN-114B and BUILD-BRAIN-114C were integrated there. It reuses the current repository identity reader, Git checkout identity, isolated-workspace marker, and allowlisted engineering path boundary rather than replaying a stale stacked branch.

## Implemented

- Adds autonomous role `isolated_workspace_static_validator`.
- Requires the exact disposable isolation marker for the requested repository and `autonomy/*` branch.
- Accepts only explicit file paths and expected SHA-256 post-patch hashes.
- Restricts validation to `app/`, `tests/`, and `docs/brain/`.
- Rejects traversal, protected paths, duplicate targets, invalid digests, excessive file counts, oversized files, aggregate byte overflow, missing files, symlinks/path escapes, branch mismatch, and mutation intent.
- Validates UTF-8 for every target.
- For Python files, parses with `ast.parse` and compiles the AST object with Python's built-in `compile` function without importing or executing the changed module and without writing bytecode.
- Non-Python text receives deterministic hash and UTF-8 validation with syntax marked not applicable.
- Rechecks checkout identity after the scan.
- Emits deterministic authoritative receipts with immutable starting commit, target hashes, byte counts, language/syntax states, and explicit negative authority claims: repository code not imported/executed, no subprocess, no shell, no network, no file writes.
- Registers repository-code execution independently from workspace mutation and external side effects.

## What this does not validate

Static validation is intentionally narrower than CI. It does not prove Ruff/lint success, unit/integration test success, dependency compatibility, runtime route mounting, database behavior, browser behavior, network integration, or packaging/build success. Those require a future sandboxed executable validation layer.

## Validation coverage

Focused tests cover hash-bound Python syntax validation, invalid Python rejection, stale post-patch hash rejection, UTF-8/hash validation for Brain documentation, path escape/protected-path/duplicate rejection, branch/marker/non-mutating guards, and registry classification as authoritative but non-mutating and non-executing.

Dedicated workflow: `.github/workflows/build-brain-114d.yml`.

The 2026-08-07 zero-step Actions incident is resolved. Account inspection showed the Actions product budget at `$0` with stop-usage enabled; raising it to `$25/month` restored normal hosted-runner execution while retaining a hard monthly stop and threshold alerts.

## Autonomy significance

With BUILD-BRAIN-114B through 114D on the current-main lineage, the engineering loop has three bounded authoritative primitives: inspect immutable repository evidence, modify an explicitly disposable isolated worktree using exact preimage hashes, and independently verify resulting file hashes and Python syntax without executing repository code.

The next integration slice is persisted job-input wiring for patch→static-validation program execution. A later, separately governed milestone can introduce sandboxed executable validation. Merge and deployment authority remain outside the autonomous boundary.
