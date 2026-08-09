# BUILD-BRAIN-114M-R1 → 114R strengthened handoff

## Authoritative chain

The autonomy proposal trust chain has been reconstructed again from the exact strengthened BUILD-BRAIN-114M-R1 parent after canonical assignment-input verification and worker-cycle integration became part of the root trust contract.

Current authoritative sequence:

1. **#696 — BUILD-BRAIN-114M-R1**: durable persisted patch provenance, canonical assignment inputs, role-scoped `workspace_write`, end-to-end worker-cycle execution, and manifest v2.
2. **#747 — BUILD-BRAIN-114N-R2**: exact-manifest operational/security review evidence on the strengthened root.
3. **#749 — BUILD-BRAIN-114P-R2**: durable tamper-evident review registry on #747, with fixtures corrected to the canonical input checksum.
4. **#753 — BUILD-BRAIN-114O-R2**: durable-reviewed owner authorization request v2 on #749.
5. **#756 — BUILD-BRAIN-114Q-R2**: public-key-only Ed25519 owner-grant verification on #753.
6. **current 114R-R2 draft**: deterministic authorization-bound execution plan v2 on #756.

Historical branches #687, #719, #721, #724, #726, #728 and earlier predecessors are superseded/being retired and are not integration paths.

## Trust invariants preserved end to end

- exact durable `patch_program_job_id` is preserved from persisted execution through manifest, review records, owner request, and execution plan;
- persisted patch evidence must match the canonical assignment input checksum derived from durable program/job state;
- only the isolated patch role receives `workspace_write`;
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

Canonical incident #481 remains the blocking validation dependency: GitHub-hosted jobs terminate before workflow step 1 with `steps=null`, including a zero-dependency `echo` workflow. Such runs provide no compile, Ruff, pytest, or diff-hygiene verdict. No current-parent autonomy PR should merge until exact unchanged heads obtain executable CI and pass.

## Next executable engineering action

When hosted runner allocation resumes:

1. validate #696 exact head;
2. validate #747, #749, #753, #756, and 114R-R2 in dependency order without changing already-valid heads;
3. fix any actual executable failures before advancing;
4. only after the entire chain is green consider normal merge review in dependency order.

The separate proposal side-effect executor milestone remains blocked on an explicit governance decision even after CI becomes green.
