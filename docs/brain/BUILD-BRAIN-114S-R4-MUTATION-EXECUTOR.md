# BUILD-BRAIN-114S-R4 — Current-main bounded proposal mutation executor

## Objective

Reconstruct BUILD-BRAIN-114S directly on current canonical `main` after the historical R3 branch fell 147 commits behind, while closing the three material Codex review findings without widening authority.

## Current trust root

The merged autonomy trust chain is:
`114M-R3 #772 → 114N #781 → 114P #782 → 114O #783 → 114Q #784 → 114R #785`.

R4 starts from current `main` and adds only the mutation executor, its focused tests, this Brain record, and its read-only validation workflow. Historical #791 remains source material and must not be merged after R4 validation.

## Review hardening

1. **P1 — authorization freshness before every remote mutation.** The executor still reconstructs and verifies the exact 114R plan before the loop, and now additionally calls `authorization_gate.verify_grant(request, grant_mapping)` immediately before every adapter operation. If an earlier operation stalls past grant expiry, no later side effect is attempted.
2. **P2 — reviewed base branch binding.** Merged 114R already binds `base_ref` into the authorization request, plan digest, and `open_pull_request` operation. R4 carries `base_ref` into mutation receipts and requires returned PR evidence to match both reviewed `base_ref` and exact `base_commit_sha`.
3. **P2 — specific failure evidence.** Partial-failure receipts now prefer a structured exception `code`, otherwise preserve the non-empty exception message, and fall back to the exception class only when no message exists. Wrong push SHA, wrong PR target, invalid PR number, expired authorization, and remote transport failures therefore remain distinguishable.

The mutation receipt schema advances to `calyx-git-proposal-mutation-receipt-v3` so review-defective R3 receipts cannot be confused with R4 evidence.

## Validation contract

Focused tests cover:
- exact successful branch → commit → push → PR flow;
- dependency-closed action prefixes;
- grant expiration between verified side effects, proving the next adapter call is never made;
- exact failure code for wrong pushed commit;
- remote exception-message preservation;
- reviewed base-ref mismatch rejection;
- strict positive non-boolean PR number validation.

Dedicated CI compiles and Ruff-checks the R4 surfaces, runs both R4 mutation regressions and merged 114R plan regressions, statically asserts the review fixes and permanent authority boundary, and runs diff hygiene.

## Permanent authority boundary

R4 contains only an injected adapter protocol. It does not contain or activate GitHub credentials, a network transport, Git CLI/subprocess execution, merge or auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. Live adapter/credential activation remains a separate operations and owner-governance decision. Merge of the executor core remains governed by issue #729.
