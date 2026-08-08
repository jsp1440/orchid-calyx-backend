# BUILD-BRAIN-114M — Evidence-bound Git proposal manifest

## Objective

Advance Calyx from validated autonomous engineering work toward Git/PR proposal readiness without granting Git or GitHub mutation authority. BUILD-BRAIN-114M converts an authoritative isolated patch receipt plus successful external-sandbox validation evidence into a deterministic, reviewable proposal manifest.

## Implemented

- deterministic `calyx-git-proposal-manifest-v1` envelope;
- exact repository, source autonomy branch, and base checkout commit inherited from the authoritative isolated patch receipt;
- exact isolated-patch output checksum verification before proposal creation;
- bounded changed-file set preserving before/after SHA-256, creation state, and size without including file contents;
- proposed branch restricted to the `autonomy/proposal/*` namespace and prohibited from being the source work branch;
- exact external validation request/receipt verification using BUILD-BRAIN-114K contracts;
- validation identity must match the patch repository, autonomy branch, and base checkout commit;
- only successful `delivered` / return-code-zero supervisor evidence is accepted;
- every changed Python postimage must be covered by successful Ruff evidence with the exact postimage hash;
- changed test Python files require successful pytest evidence;
- deterministic proposal digest binds patch output checksum, changes, validation request/receipt/policy digests, proposal branch, commit title, PR title, and summary;
- explicit permanent false authority flags for Git mutation, commit, push, pull-request creation, automatic merge, deployment, publication, production database mutation, and production Knowledge Graph mutation;
- focused tests and a dedicated read-only CI gate.

## Why this slice matters

The autonomous engineering chain can now produce a bounded patch, validate it independently through the external sandbox boundary, and assemble a deterministic proposal package that a later Git-authority component can consume. The proposal package itself performs no Git or GitHub operations. This separates engineering evidence from repository mutation authority and gives reviewers a stable cryptographic object to approve or reject.

## Evidence requirements

A proposal cannot be generated from a dry run, an unverified patch checksum, a mismatched repository/revision, blocked or timed-out validation, stale validation hashes, incomplete Ruff coverage of changed Python files, or an arbitrary branch namespace.

## Permanent non-authorities

BUILD-BRAIN-114M performs no Git command, commit, branch creation, push, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. It stores no credentials and performs no network calls.

## Validation contract

The dedicated BUILD-BRAIN-114M workflow compiles the new surface, runs Ruff, executes focused proposal regressions, statically asserts the absence of Git/network mutation mechanisms, and runs diff hygiene. Exact-head CI must be green before the slice is considered review-ready.
