# BUILD-BRAIN-114R — Authorization-bound Git proposal execution plan

## Objective

Compile the exact reviewed and owner-approved proposal evidence chain into a deterministic Git/GitHub **plan**, while still performing no repository mutation.

114R is the final evidence/planning layer before any future branch/commit/push/pull-request executor. It intentionally stops at that governance boundary.

## Input trust chain

`GitProposalExecutionPlanner.build()` does not accept a caller-constructed authorization object as sufficient authority. At plan time it:

1. rebuilds the 114O authorization request from the exact manifest and current durable 114P review store;
2. compares the rebuilt request snapshot to the supplied request exactly;
3. therefore rechecks manifest digest, repository/base commit, proposal branch, postimage hashes, validation receipt digests, durable review authorization digests, allowlisted actions, and expiry;
4. asks the configured 114O gate to verify the supplied owner grant again through the 114Q signature verifier; and
5. only then emits a plan.

If durable review evidence is missing, rejected, conflicted, tampered, or changed since authorization, request reconstruction fails closed. If the owner signature is invalid/revoked or the grant has expired, no plan is produced.

## Deterministic plan

The plan is bound to:

- exact manifest digest;
- exact 114O request digest;
- repository and base commit;
- `autonomy/proposal/*` branch;
- changed-file postimage SHA-256 values;
- validation receipt digests;
- durable security/operational authorization digests;
- owner principal and grant expiry;
- a SHA-256 digest of the exact verified signature envelope;
- commit title, PR title, and summary from the exact manifest; and
- the authorized action set.

Operations are emitted in canonical dependency order regardless of the order in which the allowlisted actions appeared in the authorization request:

1. `create_branch`
2. `create_commit`
3. `push_branch`
4. `open_pull_request`

Only authorized actions appear. Subsets remain subsets; planning never broadens authority.

The plan contains descriptive parameters only. It contains no command strings, credentials, tokens, write endpoints, mutation clients, subprocess calls, Git invocations, or GitHub API calls.

## Non-authority assertions

Every plan snapshot explicitly records `plan_only=true` and keeps all mutation/activation authorities false: no branch was created, no commit was created, no push occurred, no pull request was created, and merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation are not authorized.

`owner_grant_verified=true` means only that the grant was reverified while compiling this evidence object. It does not itself execute or grant any operation beyond the action names already present in the owner-bound 114O request.

## Validation

Focused regressions cover deterministic plan digests, complete evidence binding, canonical action ordering and subsets, request mismatch, manifest tampering, missing/rejected durable review evidence, invalid owner signature, expired authorization, and explicit non-mutation assertions.

The dedicated workflow also statically prohibits subprocess/Git/HTTP/GitHub mutation implementation markers in the 114R runtime planner.

Canonical CI incident #481 remains active: a hosted run that terminates with `steps=null` before step 1 is infrastructure evidence, not an executable code verdict.

## Governance boundary

The next architectural step would be an executor that actually creates a branch, creates a commit, pushes a branch, and opens a pull request from this plan. **That step crosses from evidence generation into real external side effects and remains a separate governance decision.**

114R does not authorize merge or auto-merge under any circumstances, and it does not authorize deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.
