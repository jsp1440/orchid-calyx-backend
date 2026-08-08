# BUILD-BRAIN-114N — Git Mutation Authorization Gate

## Status

Implemented as a non-mutating governance layer after BUILD-BRAIN-114M.

## Purpose

BUILD-BRAIN-114M can produce an evidence-bound Git proposal manifest but explicitly carries no authority to mutate Git or GitHub. BUILD-BRAIN-114N defines the exact authorization envelope required before any future executor may create a branch, create a commit, push a proposal branch, or open a pull request.

This build does **not** perform any Git command, network call, GitHub mutation, merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

## Authorization request

The gate accepts only an intact `calyx-git-proposal-manifest-v1` snapshot whose `manifest_digest` recomputes exactly and whose authority flags remain false. It binds an authorization request to:

- exact proposal manifest digest;
- repository identity;
- exact 40-character base commit SHA;
- `autonomy/proposal/*` target branch;
- every changed path and postimage SHA-256;
- every successful validation receipt digest;
- an explicit allowlisted action set;
- a short expiration time, capped at 30 minutes.

Only these action names are eligible for this envelope:

- `create_branch`
- `create_commit`
- `push_branch`
- `open_pull_request`

Merge, auto-merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation remain outside the authorization surface.

## Owner decision verification

A grant must be bound to the exact authorization request digest, identify the configured owner principal, carry an explicit `approved` decision, match the request expiration, remain unexpired, and pass HMAC-SHA-256 verification using an externally supplied high-entropy secret. A denial, wrong principal, wrong request digest, expired grant, modified signature, manifest drift, or authority-contaminated manifest fails closed.

The secret is not persisted by this module and no default secret exists. Deployment or secret provisioning is intentionally outside this build.

## Security properties

1. Proposal evidence cannot silently turn into mutation authority.
2. Approval is exact-request-bound rather than a reusable blanket permission.
3. Approval expires quickly and cannot authorize merge/deploy/publication/production mutation.
4. Manifest changes invalidate the request digest and therefore invalidate prior authorization.
5. The gate contains no subprocess, shell, Git, HTTP, GitHub, database, or deployment executor.
6. The dedicated CI job has `contents: read` only and statically rejects mutation/network execution surfaces.

## Validation

Dedicated CI compiles the gate, runs Ruff, executes focused regressions for exact binding/tamper detection/owner verification/denial/signature failure/expiration, asserts the non-mutation boundary, and checks diff hygiene.

## Governance boundary after 114N

The next engineering slice would be a real Git/GitHub proposal executor consuming a verified 114N grant. That component would introduce repository and network mutation authority. It must remain separate from this gate and should not be activated, merged with production credentials, or granted autonomous use without an explicit governance decision defining scope, credential custody, revocation, audit retention, and whether pull-request creation may occur without per-request owner approval.
