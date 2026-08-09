# BUILD-BRAIN-114M → 114R current-main handoff

## Authoritative chain

The autonomy proposal trust chain is now reconstructed from current `main` rather than the closed stale BUILD-BRAIN-114M-R1 ancestry.

Current authoritative sequence:

1. **#761 — BUILD-BRAIN-114M-R2** — head `55bced0b862fa088a61db67580d95496f5eb3a2d`: current-main durable persisted patch provenance, canonical assignment inputs, role-scoped `workspace_write`, durable receipt identity, exact patch input/output verification, and manifest v2.
2. **#762 — BUILD-BRAIN-114N-R3** — head `c5c6c5b8122531ceb286ea15d71b5f20c85397e6`: exact-manifest operational/security review evidence on #761.
3. **#763 — BUILD-BRAIN-114P-R3** — head `0e7151f2e8fd855b57d1265fd40de40148047dbd`: durable tamper-evident review registry on #762.
4. **#765 — BUILD-BRAIN-114O-R3** — head `2fbe21ba9a6fd9d1e3a3ee12b87610a81ddb43e9`: durable-reviewed owner authorization request v2 on #763.
5. **#766 — BUILD-BRAIN-114Q-R3** — head `e62f6004b4abb9449f91e3fa67d3d035c1b754ec`: public-key-only Ed25519 owner-grant verification on #765.
6. **#767 — BUILD-BRAIN-114R-R3**: deterministic authorization-bound execution plan v2 on #766, with no Git/GitHub side effects.

Historical #696/#747/#749/#753/#756/#760 and earlier predecessors are superseded by this current-main sequence and are not integration paths.

## Trust invariants preserved end to end

- exact durable `patch_program_job_id` is preserved from persisted execution through manifest, review records, owner request, and execution plan;
- persisted patch evidence must match the canonical assignment input checksum derived from durable program/job state;
- only the isolated patch role receives `workspace_write`;
- caller-supplied patch receipts cannot establish proposal provenance;
- operational and security reviews are exact-manifest-bound, durable, independently reviewed, and reverified on read;
- owner authorization is short-lived and bound to the exact request digest;
- owner signature verification uses public Ed25519 material only, supports explicit rotation/revocation, and preserves case-sensitive signature envelopes;
- the plan re-derives the request from current durable evidence and re-verifies the owner grant at plan time;
- planned operations must be dependency-closed and canonical;
- no layer silently broadens authority.

## Permanent non-authorities through 114R

No layer in #761→#767 performs or authorizes merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

#767 is **plan-only**. It does not execute branch creation, commit creation, push, or pull-request creation. Implementing those external side effects is BUILD-BRAIN-114S and remains a separate explicit owner-governance boundary.

## Validation state

Every current-main PR contains focused tests, compile/lint contracts, static authority-boundary checks, diff hygiene, and dedicated read-only GitHub Actions validation.

Canonical incident #481 remains the external validation blocker. Current R3 evidence includes:

- #765 BUILD-BRAIN-114O run `31292694580`, job `93192504948` — `steps=null` before checkout;
- #766 BUILD-BRAIN-114Q run `31292752980`, job `93192665401` — `steps=null` before checkout;
- #767 BUILD-BRAIN-114R run `31292890637`, job `93193044603` — `steps=null` before checkout.

Earlier exact-head #761/#762/#763 workflows showed the same pre-step allocation failure. These are infrastructure observations only and provide no compile, Ruff, pytest, migration, or diff-hygiene verdict. Issue #481 contains the fresh #767 evidence.

No current-main autonomy PR should be marked ready or merged until its exact unchanged head receives executable CI and passes.

## Integration state

A current-main drift audit after merge commit `6dc9466442e7d5172269a451691b3e9bf5e0b5c7` found the intervening main delta changed only CALYX-455 harvester-command files, with no overlap against the nine BUILD-BRAIN-114M-R2 files. GitHub subsequently reports #761 mergeable. The stacked #762/#763/#765/#766/#767 PRs are likewise mergeable at this checkpoint.

The obsolete R2 chain #747/#749/#753/#756/#760 has been closed unmerged so there is one active autonomy integration path.

## Recovery sequence

When hosted runner allocation resumes:

1. validate #761 exact head;
2. validate #762 exact head;
3. validate #763 exact head;
4. validate #765 exact head;
5. validate #766 exact head;
6. validate #767 exact head;
7. fix real executable failures before expanding;
8. only after the full chain is green consider normal merge review in dependency order.

BUILD-BRAIN-114S remains out of scope until an explicit governance decision authorizes development of real branch/commit/push/open-PR side effects.
