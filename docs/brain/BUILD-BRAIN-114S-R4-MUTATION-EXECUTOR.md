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

### Executable exact-head receipt

Runtime/test head `a3b993709fff2486beaec140983124f5a6cf6f57` was validated through the PR merge ref against then-current canonical `main`.

- BUILD-BRAIN-114S-R4 Mutation Executor Validation run `31333396842`, run #2: **success**.
- Compile: passed.
- Ruff lint and format: passed.
- Focused 114S-R4 + merged 114R regressions: **16 passed in 0.83s**.
- Static authority/review-fix boundary: passed.
- Diff hygiene: passed.
- CALYX Workflow Governance Audit run `31333396902`, #1093: **success**.
- CALYX-AGENT-003 Validation run `31333396853`, #525: **success**.
- BUILD-088E Validation run `31333396859`, #1588: **success**.

The first R4 run failed only at Ruff import ordering before behavioral tests. That formatter-only defect was corrected on `a3b9937…`, after which all four exact-head gates above passed. This fail-first history is retained so the Brain distinguishes a real validated head from the earlier pre-test head.

The GitHub Actions runner incident recorded in #481 is therefore no longer blocking this slice: the R4 runs executed real hosted-runner steps on Ubuntu 24.04 and produced a normal test verdict.

## Permanent authority boundary

R4 contains only an injected adapter protocol. It does not contain or activate GitHub credentials, a network transport, Git CLI/subprocess execution, merge or auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation. Live adapter/credential activation remains a separate operations and owner-governance decision. Merge of the executor core remains governed by issue #729.
