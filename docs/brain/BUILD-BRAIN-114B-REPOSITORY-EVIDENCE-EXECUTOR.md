# BUILD-BRAIN-114B — Read-only repository evidence executor

## Objective

Add the first genuinely useful authoritative autonomous adapter while preserving the no-shell, no-network, no-credential boundary.

## Implemented

- Added the `repository_evidence_reader` autonomous role.
- Added `RepositoryEvidenceExecutor`, which reads only a fixed allowlist of engineering-control files from an explicitly configured local checkout.
- The executor records path, byte size, required/optional status, and SHA-256 hashes. File contents are never included in the receipt.
- Evidence is bound to the actual local Git branch plus the immutable 40-character commit SHA resolved from `.git/HEAD`, loose refs, or `packed-refs`; a job requesting a different branch is rejected before any evidence is delivered.
- The checkout identity is re-read after the evidence scan. If branch or commit changes during collection, the executor fails closed rather than publishing a receipt with stale revision context.
- Receipts explicitly identify their provenance as `local_worktree_observation`; the commit SHA supplies checkout context and is not represented as proof that the observed bytes were reconstructed from Git objects.
- Workspace confinement is enforced with descriptor-relative traversal rather than check-then-read path access. Every directory component and final file is opened with no-follow semantics where supported, the opened descriptor is validated with `fstat`, and the read itself is bounded.
- Path traversal, parent or final symlinks, non-regular files, oversized files, oversized aggregate reads, non-UTF-8 files, invalid Git metadata, repository mismatch, revision mismatch, checkout change during scan, and mutating intent fail closed.
- Required files currently include `AGENTS.md` and `requirements.txt`; optional evidence includes `pyproject.toml`, `README.md`, the BUILD-BRAIN-114A workflow, and its Brain record when present.
- The adapter is registered in `AuthoritativeExecutorRegistry` and therefore becomes eligible for the bounded autonomous worker cycle.
- The adapter is authoritative only for read-only repository evidence collection and has no external side effects.
- Focused tests cover deterministic hashes, content exclusion, mutation rejection, repository mismatch, revision mismatch, detached-checkout rejection, checkout-change rejection, path traversal, final and parent-directory symlink rejection, optional-file reporting, and end-to-end program completion.
- Added `scripts/validate_repository_evidence_executor.py`, a single portable validation contract for required-file inventory, Python compilation, Ruff, and the complete focused pytest surface.
- The validator writes `artifacts/validation/repository-evidence-executor.json` with exact commands, timestamps, return codes, bounded stdout/stderr tails, Python/platform metadata, failure stage, and explicit no-merge/no-deploy/no-publication/no-production-write authority.
- BUILD-BRAIN-114B GitHub Actions now delegates to that validator and emits the machine-readable receipt when the runner actually starts.

## Execution chain

`started program -> scheduler -> role-filtered claim -> governed assignment -> verified checkout revision -> descriptor-safe repository evidence read -> stable-revision recheck -> hash-only receipt -> atomic lease completion -> dependency release`

## Governance

This adapter does not use shell commands, network access, GitHub APIs, credentials, repository writes, merges, deployments, publication, taxonomy activation, or production scientific data mutation. It can only observe a configured local checkout and emit revision-contextual metadata/hashes for its fixed evidence targets.

## Review corrections

Review and static audit identified three material provenance/safety defects before merge:

1. Evidence was not originally bound to the branch/revision requested by the job. The executor now resolves the actual checkout branch and immutable commit SHA from local Git metadata and rejects mismatched or detached branch requests.
2. The original path `stat()` followed by `read_bytes()` left a TOCTOU window. The executor now opens path components and files beneath the workspace through no-follow descriptors, validates the opened file with `fstat`, and performs a bounded descriptor read.
3. Checkout identity was initially checked only before file collection. A concurrent checkout could therefore change revision during the scan. The executor now requires identical branch/commit identity before and after collection and labels the result as a local worktree observation.

All three corrections are covered by regression tests. The PR remains unmerged until executable CI runs successfully.

## Operational value

The autonomous engine can now perform one real evidence-producing task rather than merely exercising internal orchestration plumbing. This establishes the pattern for additional reviewed read-only adapters such as CI-result inspection, repository-state analysis, literature metadata acquisition, and Knowledge Graph preflight evidence.

## Validation note

GitHub Actions validation is currently failing before any workflow steps are instantiated, including pre-existing unrelated workflows. A repository-wide zero-dependency smoke workflow also fails before its single `echo` step. GitHub's public status history confirms an Actions incident on August 7, 2026 in which runners were assigned invalid jobs and some push/pull-request events could not be replayed automatically. A close/reopen of PR #527 generated fresh runs, but they still terminated with `steps=null`, so the remaining blocker is hosted-runner/account policy or residual Actions infrastructure rather than demonstrated application code failure.

No compile, Ruff, pytest, or application step has run on the affected attempts, so success is not claimed and the PR remains unmerged.
