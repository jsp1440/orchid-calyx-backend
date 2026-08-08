# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts an authoritative isolated patch receipt plus successful, persisted external-sandbox validation evidence into a deterministic, reviewable proposal manifest.

## Implemented

- deterministic `calyx-git-proposal-manifest-v1` envelope;
- exact repository, source autonomy branch, and base checkout commit inherited from the authoritative isolated patch receipt;
- exact isolated-patch output checksum verification before proposal creation;
- bounded changed-file set preserving before/after SHA-256, creation state, and size without including file contents;
- proposed branch restricted to the `autonomy/proposal/*` namespace, prohibited from being the source work branch, and validated against Git ref-name rules without invoking Git or a shell;
- external validation request/receipt verification using BUILD-BRAIN-114K contracts;
- **persisted supervisor-record authentication**: each serialized receipt must resolve through `SandboxSupervisorService.get_completed_by_digest()` to an already completed durable supervisor record, and persisted repository/branch/commit/preset/targets/timeout, receipt digest, policy digest, authorization ID, and evidence URI must match exactly;
- explicit allowed sandbox-policy digest set, so a persisted receipt created under an unapproved/obsolete worker policy cannot satisfy proposal validation;
- validation identity must match the patch repository, autonomy branch, and base checkout commit;
- only successful `delivered` / return-code-zero supervisor evidence is accepted;
- every changed Python postimage must be covered by successful Ruff evidence with the exact postimage hash;
- every changed Python test must be covered by successful pytest evidence for that exact `(path, postimage SHA-256)`, not merely by an unrelated successful pytest target;
- deterministic proposal digest binds patch output checksum, changes, validation request/receipt/policy digests, proposal branch, commit title, PR title, and summary;
- explicit permanent false authority flags for Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, production database mutation, and production Knowledge Graph mutation;
- focused tests and a dedicated read-only CI gate;
- manual `workflow_dispatch` validation chooses the repository default branch when no pull-request `base_ref` exists, so diff hygiene remains executable outside PR events.

## Post-review corrections

Four review findings were accepted before merge:

1. **P1 — fabricated supervisor receipt.** Shape validation plus a caller-computable request digest was insufficient. 114M now requires a matching persisted completed record from the 114K supervisor service and an allowed policy digest. A serialized `delivered` receipt whose receipt digest differs from the durable record is rejected.
2. **P2 — incomplete pytest coverage.** Changed tests now require exact pytest target coverage by path and postimage hash, mirroring Ruff coverage semantics.
3. **P2 — invalid future branch names.** Proposal branch validation now implements Git ref-name constraints in pure Python while preserving the `autonomy/proposal/*` namespace and no-Git-execution boundary.
4. **P2 — manual workflow diff base.** Diff hygiene now uses `github.base_ref` for PRs or the repository default branch for manual dispatch runs.

These corrections narrow trust; none grants Git, GitHub, deployment, publication, production database, taxonomy, or Knowledge Graph mutation authority.

## Why this slice matters

The autonomous engineering chain can produce a bounded patch, validate it independently through the external sandbox boundary, prove that the validation receipt is the same receipt durably accepted by the authenticated supervisor service, and assemble a deterministic proposal package that a later Git-authority component could consume. The proposal package itself performs no Git or GitHub operations. This separates engineering evidence from repository mutation authority and gives reviewers a stable cryptographic object to approve or reject.

## Evidence requirements

A proposal cannot be generated from a dry run, an unverified patch checksum, a mismatched repository/revision, a fabricated or unpersisted supervisor receipt, an unapproved sandbox policy, blocked or timed-out validation, stale validation hashes, incomplete Ruff coverage of changed Python files, incomplete exact pytest coverage of changed tests, or a Git-invalid/arbitrary branch namespace.

The persisted supervisor record is the trust anchor for serialized external-validation evidence. 114M never accepts a caller-provided `trusted=true` flag or a receipt solely because its fields are structurally valid.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, commit, branch creation, push, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls. Its added supervisor-service operation is read-only durable-record lookup.

## Validation contract

The dedicated BUILD-BRAIN-114M workflow compiles the manifest and persisted-record lookup surfaces, runs Ruff lint and format checks, executes focused proposal regressions, statically asserts the absence of Git/network mutation mechanisms and the presence of persisted-evidence authority checks, and runs event-aware diff hygiene. CALYX Workflow Governance Audit and BUILD-088E remain required. Exact-head CI must be green against the current hardened BUILD-BRAIN-114L base before the slice is considered review-ready. Merge remains a separate governance decision.

## Exact-head validation provenance

The Ruff-only correction at `7ba47cc9f1f03aa9e5a166aa30e2ad301279142b` was authored by an automation identity, after which GitHub classified the subsequent pull-request workflows as `action_required` before creating any jobs. This Brain update intentionally creates a repository-owner-authored documentation head without changing runtime behavior so the same exact stacked validation matrix can execute normally. A passing result must still cover BUILD-BRAIN-114M, BUILD-BRAIN-114K, CALYX agent validation, and workflow governance on the new head before review-readiness is claimed.
