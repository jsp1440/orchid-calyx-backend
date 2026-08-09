# BUILD-BRAIN-114S — Bounded Git proposal mutation executor core

## Objective

Introduce the first executor core allowed to cross from authorization/evidence generation into bounded Git/GitHub proposal side effects. This slice remains strictly limited to the proposal actions already bound into BUILD-BRAIN-114O and recompiled by BUILD-BRAIN-114R:

1. create branch;
2. create commit;
3. push proposal branch;
4. open pull request.

No merge or auto-merge authority is introduced.

## Fresh-verification rule

`GitProposalMutationExecutor.execute()` does not trust a previously built plan merely because it exists. Immediately before the first mutation it rebuilds BUILD-BRAIN-114R from the exact manifest, durable 114P review store, 114O authorization request, and externally verified owner grant. The rebuilt plan snapshot must equal the supplied plan snapshot exactly.

Therefore manifest drift, review drift, authorization drift, expired/revoked owner approval, or altered plan text/hashes fails before adapter invocation.

## Repository and action confinement

The executor requires an explicit repository allowlist and rejects any proposal branch outside `autonomy/proposal/*`. It accepts only the four canonical proposal actions and requires canonical dependency order without duplicates.

The injected `GitProposalMutationAdapter` protocol exposes one proposal-operation method and deliberately exposes no merge, auto-merge, deployment, publication, database, taxonomy, or Knowledge Graph mutation API. The executor core itself loads no GitHub token, credential, private key, or deployment secret.

This design separates policy/evidence verification from the external mutation transport. Production credential wiring and activation remain separate operations decisions.

## Operation evidence

Every adapter response is verified before the next operation can begin. Evidence must match the exact repository and proposal branch and must use only `created` or `already_exists_exact` status.

Additional checks are action-specific:

- branch evidence must identify the exact authorized base commit;
- commit evidence must identify the exact parent commit, a valid commit SHA, and every expected postimage SHA-256;
- push evidence must identify the **same exact commit SHA** returned by the verified create-commit evidence;
- pull-request evidence must identify the exact head branch/base commit, the **same exact verified commit SHA**, and a positive PR number.

The commit-continuity checks were added during implementation review before expansion. They prevent a mutation adapter from creating an authorized commit but then pushing or opening a PR against a different commit while returning superficially valid evidence.

A divergent remote state therefore fails closed instead of being silently treated as idempotent success.

## Partial failure semantics

Remote Git/GitHub effects cannot be truthfully represented as transactional rollback. If an adapter failure occurs after earlier actions completed, the executor raises `GitProposalMutationError` carrying a deterministic partial receipt. The receipt records only operations whose returned evidence was already verified. It does not claim that an already-created branch or commit was undone.

This is necessary for safe recovery: a later worker can inspect authoritative completed-operation evidence rather than blindly repeating the entire chain.

## Activation boundary

114S implements and tests the mutation **executor core**, but this PR does not wire a production Git/GitHub credential or a live mutation adapter into the autonomous worker runtime. The adapter in focused tests is an in-memory fake.

A production adapter must separately prove least-privilege credentials, repository allowlisting, immutable workspace/postimage binding, exact idempotency behavior, audit logging, independent remote-state verification, and disabled merge/deployment scopes before activation.

## Permanent prohibitions

114S does not authorize or implement:

- merge or auto-merge;
- deployment;
- scientific publication;
- taxonomy activation;
- production database mutation;
- production Knowledge Graph mutation.

Those remain independent governance authorities.

## Validation

Focused regressions cover successful canonical branch→commit→push→PR execution through a fake adapter, fresh-plan mismatch rejection, expired owner grant rejection before mutation, repository allowlist enforcement, divergent commit-postimage rejection, wrong pushed-commit rejection, and partial-failure evidence preservation.

The dedicated CI also statically asserts that the executor core contains no subprocess/Git CLI, requests/HTTP client, GitHub credential loader, merge/auto-merge marker, deployment executor, or production mutation path.

Exact-head GitHub Actions was attempted after implementation and again after commit-continuity hardening. On code head `fdda21d8bd2a20c87b7c1fafcb894e5ec075db52`, dedicated run `31290576039`, job `93186874704`, terminated before workflow step 1 with `steps=null`. CALYX-AGENT-003 and Workflow Governance Audit on the same head failed in the same pre-step infrastructure mode. No checkout, compile, Ruff, pytest, or authority assertion executed, so these are not treated as code verdicts.

Canonical CI incident #481 remains the blocker for executable exact-head validation.
