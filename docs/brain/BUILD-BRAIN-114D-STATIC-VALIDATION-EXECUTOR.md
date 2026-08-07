# BUILD-BRAIN-114D — Read-only static validation executor

## Objective

Pair the isolated patch executor with an independent authoritative validator that checks exact post-patch bytes and Python syntax without importing or executing repository code.

## Current-main implementation

- Adds role `isolated_workspace_static_validator`.
- Requires the same repository, `autonomy/*` branch, and disposable-workspace marker boundary as BUILD-BRAIN-114C.
- Accepts a bounded list of expected file paths and exact SHA-256 postimage hashes.
- Restricts targets to the existing autonomy allowlist and reuses descriptor-safe reads from BUILD-BRAIN-114B.
- Rejects duplicate paths, missing files, hash mismatch, invalid UTF-8, path escape, protected paths, invalid marker/revision state, and checkout changes during the scan.
- Python files are parsed with `ast.parse` and compiled as syntax objects only; repository modules are never imported and repository code is never executed.
- Text files receive hash and UTF-8 validation without syntax claims.
- Receipts explicitly state `repository_code_imported=false`, `repository_code_executed=false`, `subprocess_invoked=false`, `shell_invoked=false`, `network_used=false`, `files_written=false`.
- The executor registry marks this adapter authoritative, non-mutating, and non-executing.

## Validation boundary

This is stronger than a hash-only receipt but is intentionally not equivalent to CI. It does not run Ruff, pytest, application imports, database tests, browser tests, builds, dependency installation, or network integration. A future sandboxed executable-validation adapter must own those capabilities.

## Governance

No shell/subprocess, network, credentials, file writes, Git operations, commit, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized.

This clean current-main slice supersedes stale stacked PR #540.
