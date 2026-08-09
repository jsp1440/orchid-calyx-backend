# BUILD-BRAIN-114O — Durable reviewed owner authorization

## Objective

Integrate BUILD-BRAIN-114O with hardened durable proposal construction/review so a future repository-proposal executor cannot rely on process-local reviews, caller-constructed authorization records, caller-fabricated patch receipts, or a signing secret held by the autonomous runtime.

## Current dependency chain

Authoritative PR #697 is stacked on BUILD-BRAIN-114P #694, which is stacked on BUILD-BRAIN-114N #687, which is stacked on corrective BUILD-BRAIN-114M-R1 #696.

The chain is intentionally evidence-first:

`persisted isolated patch execution → manifest v2 → persisted independent reviews → owner-bound request v2`.

No layer may drop the durable patch identity before the next layer consumes it.

## Durable review chain

The gate accepts a `DurableProposalAuthorizationStore`, not an in-memory registry supplied by the caller. 114P accepts review writes only through governed `record_review()`, whose 114N builder re-resolves `patch_program_job_id` through `PersistedPatchExecutionService` before persistence.

For the exact manifest digest, 114O reloads only digest-verified persistent evidence, requires aggregate `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`, verifies the exact persisted operational and security approvals, requires appropriate roles and distinct reviewer identities, and requires both records to identify the same durable patch job as the manifest.

A standalone caller-constructed authorization record, unpersisted approval, caller-fabricated patch receipt, self-approval, tampered persisted row, stale v1 manifest, or mismatched patch-job identity cannot satisfy the gate.

## Request and owner-grant binding

114O accepts only `calyx-git-proposal-manifest-v2` and emits `calyx-git-mutation-authorization-request-v2`.

The request digest binds:

- exact manifest digest;
- exact durable `patch_program_job_id`;
- repository/base commit;
- `autonomy/proposal/*` branch;
- every postimage hash;
- validation receipt digests;
- both durable review authorization digests;
- explicit allowlisted action set;
- expiry no more than 30 minutes in the future.

This closes the final patch-provenance detachability gap: an owner grant cannot be reused for a different persisted patch execution even if other proposal metadata were copied.

## External owner verification boundary

The runtime does not receive or store an owner signing secret. `GitMutationAuthorizationGate` accepts only an externally supplied `OwnerGrantSignatureVerifier` capability. Production authorization must provide a verifier whose signing authority remains outside the autonomous runtime; the concrete external verifier is a separate deployment/trust boundary and is not activated by this PR.

The signed grant must match the exact request digest, configured owner principal, and request expiry. Its own `issued_at → expires_at` lifetime must be positive and no longer than 30 minutes. Focused tests keep HMAC only in a test-local verifier so runtime source contains neither HMAC/hashlib signing primitives, a signing secret, nor a grant-minting method.

## Allowed future proposal actions

The authorization envelope can name only `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`. This slice implements none of those mutations; it creates and verifies authorization evidence only.

## Permanent boundaries

No merge or auto-merge, deployment, publication, taxonomy activation, production operator database mutation, or production Knowledge Graph mutation authority is included. No Git command, subprocess, HTTP/GitHub mutation client, deployment system, publication system, or production-data mutation executor exists in the 114O runtime surface.

## Validation contract

The dedicated read-only workflow compiles the persisted-patch, 114N, 114P, and 114O surfaces; Ruff-checks the changed durable-store/owner-gate paths; runs focused persistence/review/patch-identity/external-verifier/owner-grant regressions; asserts manifest/request v2 plus `patch_program_job_id` binding; statically asserts runtime has no signing secret or mutation API; and runs diff hygiene.

## Current CI incident

Canonical CI issue #481 records GitHub-hosted jobs terminating before step 1 with `steps=null`. A zero-dependency diagnostic containing only one `echo` step reproduced the failure, so such attempts provide no application-code verdict.

Keep #697 draft until #696, #687, #694, and #697 exact-head merge contexts receive executable workflow steps and pass.

## Governance boundary

Only after durable patch evidence, durable independent review evidence, genuinely external owner-signature verification, and executable exact-head validation are green should the project consider a bounded Git proposal executor. Granting branch/commit/push/PR proposal authority is a separate governance decision. Merge, deployment, publication, taxonomy activation, and production scientific-data mutation remain separate authorities even after proposal execution is enabled.
