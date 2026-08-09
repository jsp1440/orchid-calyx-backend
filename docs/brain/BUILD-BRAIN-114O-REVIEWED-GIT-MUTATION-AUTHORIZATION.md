# BUILD-BRAIN-114O — Reviewed owner-bound Git mutation authorization

## Objective

Create a non-mutating authorization boundary between reviewed BUILD-BRAIN-114M proposal evidence and any future Git/GitHub proposal executor.

## Current parent

Authoritative PR #689 is stacked on BUILD-BRAIN-114N PR #687, which is itself stacked on corrective BUILD-BRAIN-114M-R1 PR #696. This dependency chain is intentional: owner authorization must not exist until proposal construction and review evidence both authenticate the same durable patch execution.

## Required evidence

114O accepts only an exact `calyx-git-proposal-manifest-v2` after 114N has stored both required review classes in the authoritative `ProposalAuthorizationRegistry` for that same manifest digest. It does not trust caller-supplied review objects.

The v2 manifest and every 114N authorization record bind the exact durable `patch_program_job_id`. `proposal_review_status()` must report `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`; the gate then retrieves exact `operational` and `security` records, verifies both against the manifest, requires both approvals from distinct reviewers, and requires both review records to identify the same patch program job as the manifest.

This prevents an owner grant from being detached from the exact persisted isolated-patch execution even if repository/branch/change metadata otherwise match.

## Request binding

The owner-authorization request schema is `calyx-git-mutation-authorization-request-v2`. Its deterministic request digest binds:

- exact v2 manifest digest;
- exact durable `patch_program_job_id`;
- repository and 40-character base commit;
- `autonomy/proposal/*` branch;
- every changed-file postimage SHA-256;
- every validation receipt digest;
- both authoritative 114N authorization digests;
- explicit allowlisted action set;
- expiry no more than 30 minutes in the future.

Allowed future action names remain limited to `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`.

## Owner grant

The runtime authorization gate is **verifier-only**. An externally controlled owner principal and HMAC-SHA-256 secret are used only to verify an externally supplied grant bound to the exact request digest. The production gate contains no method that can mint, sign, approve, or fabricate an owner grant.

A structural audit removed the earlier runtime grant-signing helper; test signing exists only in focused test code.

Grant verification enforces temporal freshness independently of request creation. Signed expiry must exactly match request expiry, and the grant's own `issued_at → expires_at` lifetime must be positive and no longer than 30 minutes. Wrong request, wrong owner, denial, invalid signature, stale issue time, future-issued grant, mismatched expiry, or expired grant fails closed.

## Permanent boundaries

114O performs no Git or GitHub mutation. It grants no merge or auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority. It contains no Git, subprocess, HTTP, deployment, publication, or production-mutation executor.

Actual branch/commit/push/PR creation remains a separate governance milestone and is not implemented here.

## Validation contract

Dedicated CI compiles the 114O/114N/persisted-patch surfaces, runs Ruff, executes focused registry/review/owner-expiry regressions, asserts that the v2 request contains the durable patch program-job identity, statically asserts the verifier-only/non-mutation boundary, and runs diff hygiene.

## Current CI incident

Canonical issue #481 records repository jobs terminating before checkout with `steps=null`. The zero-dependency diagnostic PR #690 contained only a single shell `echo` step and still failed before step 1, which rules out repository code, Python/PostgreSQL setup, checkout/setup actions, and third-party actions as the immediate cause.

Such attempts provide no code verdict. Keep #689 draft until #696 and #687 receive executable exact-head validation and #689 itself executes real workflow steps and passes.
