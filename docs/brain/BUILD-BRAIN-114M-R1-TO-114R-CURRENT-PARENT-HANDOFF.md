# BUILD-BRAIN-114M → 114R current-main handoff

## Authoritative chain

The autonomy proposal trust chain is reconstructed from current `main`; stale R1/R2 ancestry is closed and no longer an integration path.

Current authoritative sequence:

1. **#761 — BUILD-BRAIN-114M-R2** — head `5bbc2b2dcb52f782bbfb9f76494d5531634b8ef5`: current-main durable persisted patch provenance, canonical assignment inputs, exact durable receipt identity, exact patch input/output verification, manifest v2, and role-plus-intent-scoped workspace mutation.
2. **#762 — BUILD-BRAIN-114N-R3** — head `06a67ad1b1455c4d621cc790376f525cea835509`: exact-manifest operational/security review evidence on the latest #761 trust root.
3. **#763 — BUILD-BRAIN-114P-R3** — head `d04d736af883167cf99974ea0c666ead83b4a9ad`: durable tamper-evident review registry on #762.
4. **#765 — BUILD-BRAIN-114O-R3** — head `375242a3c98b15479812352e35913f8d71591846`: durable-reviewed owner authorization request v2 on #763.
5. **#766 — BUILD-BRAIN-114Q-R3** — head `6f5476098384e01af91144746d80e4b7de883157`: public-key-only Ed25519 owner-grant verification on #765.
6. **#767 — BUILD-BRAIN-114R-R3** — head before this documentation checkpoint `741b4eb664f0aeb73615701baa854b058fa2a8e4`: deterministic authorization-bound execution plan v2 on #766, with no Git/GitHub side effects.

Historical #696/#747/#749/#753/#756/#760/#768 and earlier predecessors are superseded or closed and are not integration paths.

## Root hardening propagated end to end

The latest #761 correction makes `workspace_write` available only when both conditions are true: durable role `isolated_workspace_patcher` and explicit durable `mutating=True`. A patch-role job with non-mutating intent fails closed with `ISOLATED_PATCH_MUTATING_JOB_REQUIRED`. The governance mode becomes `bounded_isolated_workspace_mutation` only for the same role-plus-intent combination.

That root correction was propagated through #762 → #763 → #765 → #766 → #767 using merge commits that preserve each layer's bounded files while making the immediately preceding updated layer an ancestor. All five stacked PRs were reported mergeable after propagation.

Other preserved trust invariants:

- exact durable `patch_program_job_id` from execution through manifest, review records, owner request, and plan;
- canonical assignment-input checksum recomputed from durable program/job state;
- caller-supplied patch receipts cannot establish proposal provenance;
- operational/security reviews remain durable, exact-manifest-bound, independently reviewed, and reverified on read;
- owner authorization is short-lived and request-digest-bound;
- owner signature verification uses public Ed25519 material only with explicit rotation/revocation and case-sensitive envelopes;
- the plan re-derives the request from current durable evidence and re-verifies the owner grant at plan time;
- planned operations must be dependency-closed and canonical;
- no layer silently broadens authority.

## Permanent non-authorities through 114R

No layer in #761→#767 performs or authorizes merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

#767 is **plan-only**. It executes no branch creation, commit creation, push, or pull-request creation. BUILD-BRAIN-114S remains a separate explicit owner-governance boundary.

## Validation state

Every current-main PR contains focused tests, compile/lint contracts, static authority-boundary checks, diff hygiene, and dedicated read-only GitHub Actions validation.

Canonical incident #481 remains the executable-validation blocker. Exact-head evidence after the latest root hardening includes:

- #761 BUILD-BRAIN-114M run `31293045940`, job `93193474127` — `steps=null` before checkout;
- #767 BUILD-BRAIN-114R run `31293152963`, job `93193768459` — `steps=null` before checkout.

Earlier #762/#763/#765/#766 exact-head attempts showed the same pre-step allocation failure. These are infrastructure observations only and provide no compile, Ruff, pytest, migration, or diff-hygiene verdict. Fresh evidence is recorded on issue #481.

No current-main autonomy PR should be marked ready or merged until its exact unchanged head receives executable CI and passes.

## Integration state

A drift audit after main merge `6dc9466442e7d5172269a451691b3e9bf5e0b5c7` found the intervening main delta changed only CALYX-455 harvester-command files and did not overlap BUILD-BRAIN-114M-R2. GitHub reports #761 mergeable.

The stale R2 chain #747/#749/#753/#756/#760 and competing #768 have been closed unmerged so there is one active autonomy integration path.

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
