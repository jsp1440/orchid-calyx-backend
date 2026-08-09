# BUILD-BRAIN-114M-R1 → 114R current-parent handoff

## Authoritative chain

The autonomy proposal trust chain has been reconstructed from exact current parents after 114M-R1 advanced its persisted-patch provenance contract.

Current authoritative sequence:

1. **#696 — BUILD-BRAIN-114M-R1**: durable persisted patch provenance and manifest v2 foundation.
2. **#719 — BUILD-BRAIN-114N**: governed operational/security review evidence, rebuilt directly on the exact current #696 head.
3. **#721 — BUILD-BRAIN-114P**: durable tamper-evident review registry, rebuilt directly on #719.
4. **#724 — BUILD-BRAIN-114O**: durable-reviewed owner authorization request v2, rebuilt directly on #721.
5. **#726 — BUILD-BRAIN-114Q**: public-key-only Ed25519 owner-grant verification, rebuilt directly on #724.
6. **#728 — BUILD-BRAIN-114R**: deterministic authorization-bound execution plan v2, rebuilt directly on #726.

Historical/stale branches #687, #694, #697, #700, #702, #708, #717, and #718 are closed unmerged and are no longer integration paths.

## Trust invariants preserved end to end

- exact durable `patch_program_job_id` is preserved from persisted execution through manifest, review records, owner request, and execution plan;
- caller-supplied patch receipts cannot establish proposal provenance;
- operational and security reviews must be durable, approved, exact-manifest-bound, and from distinct reviewers;
- owner authorization is short-lived and bound to the exact request digest;
- owner signature verification uses public Ed25519 material only and preserves case-sensitive signature envelopes;
- the plan re-derives the request from current durable evidence and re-verifies the owner grant at plan time;
- planned operations must be dependency-closed and canonical;
- no layer silently broadens authority.

## Permanent non-authorities through 114R

No current layer performs or authorizes merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

114R is **plan-only**. It does not execute branch creation, commit creation, push, or pull-request creation. Implementing those external side effects is the next governance boundary and requires a separate owner decision.

## Validation state

Each current-parent PR includes focused tests, compilation/lint contracts, static authority-boundary checks, diff hygiene, and dedicated read-only GitHub Actions validation.

Canonical incident #481 remains the blocking validation dependency: GitHub-hosted jobs are allocated as runs but terminate before workflow step 1 with `steps=null`. Such runs provide no compile, Ruff, pytest, or diff-hygiene verdict. No current-parent PR should merge until the exact unchanged heads obtain executable CI and pass.

## Next executable engineering action

When hosted runner allocation resumes:

1. validate #696 exact head;
2. validate #719, #721, #724, #726, and #728 in dependency order without changing already-valid heads;
3. fix any actual executable failures before advancing;
4. only after the entire chain is green consider normal merge review in dependency order.

The separate proposal-executor milestone remains blocked on an explicit governance decision even after CI becomes green.
