# BUILD-BRAIN-114B — Read-only repository evidence executor

## Objective

Add the first genuinely useful authoritative autonomous adapter while preserving the no-shell, no-network, no-credential boundary.

## Implemented

- Added the `repository_evidence_reader` autonomous role.
- Added `RepositoryEvidenceExecutor`, which reads only a fixed allowlist of engineering-control files from an explicitly configured local checkout.
- The executor records path, byte size, required/optional status, and SHA-256 hashes. File contents are never included in the receipt.
- Workspace-root confinement is enforced after path resolution. Path escape, symlinks, non-regular files, oversized files, oversized aggregate reads, non-UTF-8 files, repository mismatch, and mutating intent fail closed.
- Required files currently include `AGENTS.md` and `requirements.txt`; optional evidence includes `pyproject.toml`, `README.md`, the BUILD-BRAIN-114A workflow, and its Brain record when present.
- The adapter is registered in `AuthoritativeExecutorRegistry` and therefore becomes eligible for the bounded autonomous worker cycle.
- The adapter is authoritative only for read-only repository evidence collection and has no external side effects.
- Focused tests cover deterministic hashes, content exclusion, mutation rejection, repository mismatch, path escape, symlink rejection, optional-file reporting, and end-to-end program completion.

## Execution chain

`started program -> scheduler -> role-filtered claim -> governed assignment -> repository evidence reader -> hash-only receipt -> atomic lease completion -> dependency release`

## Governance

This adapter does not use shell commands, network access, GitHub APIs, credentials, repository writes, merges, deployments, publication, taxonomy activation, or production scientific data mutation. It can only observe a configured local checkout and emit metadata/hashes for its fixed evidence targets.

## Operational value

The autonomous engine can now perform one real evidence-producing task rather than merely exercising internal orchestration plumbing. This establishes the pattern for additional reviewed read-only adapters such as CI-result inspection, repository-state analysis, literature metadata acquisition, and Knowledge Graph preflight evidence.
