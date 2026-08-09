# BUILD-BRAIN-114M-R1 → 114R strengthened handoff

## Authoritative chain

The autonomy proposal trust chain has been reconstructed from the exact strengthened BUILD-BRAIN-114M-R1 parent after canonical assignment-input verification and worker-cycle integration became part of the root trust contract.

Current authoritative sequence:

1. **#696 — BUILD-BRAIN-114M-R1** — head `0571ceb6de79faf569f6acc0b0e05383547b5cd5`: durable persisted patch provenance, canonical assignment inputs, role-scoped `workspace_write`, end-to-end worker-cycle execution, and manifest v2.
2. **#747 — BUILD-BRAIN-114N-R2** — head `12f825c2f511f6146f4b0303653bdc8c3dc11e25`: exact-manifest operational/security review evidence on the strengthened root.
3. **#749 — BUILD-BRAIN-114P-R2** — head `e41f899ae362d4309b08d11797dcddc875fc3dbe`: durable tamper-evident review registry on #747, with fixtures corrected to the canonical input checksum.
4. **#753 — BUILD-BRAIN-114O-R2** — head `40d70fc8090211ee92152c6c82b57dff40e8945b`: durable-reviewed owner authorization request v2 on #749, with canonical-input receipt fixtures.
5. **#756 — BUILD-BRAIN-114Q-R2** — head `e56f34bba981380032c37597de41dc886151f642`: public-key-only Ed25519 owner-grant verification on #753.
6. **#760 — BUILD-BRAIN-114R-R2** — execution-plan head beneath this receipt `4a9c531dae7a9dbbdd5b71a49c535a46bdc38951`: deterministic authorization-bound execution plan v2 on #756, with canonical-input receipt fixtures.

Historical branches #687, #719, #721, #724, #726, #728 and earlier predecessors are superseded/closed and are not integration paths.

## Exact integration comparison receipt

GitHub compare results recorded on 2026-08-08 PT:

- #696 → #747: **6 ahead / 0 behind**, exactly six 114N files.
- #747 → #749: **6 ahead / 0 behind**, exactly six 114P files.
- #749 → #753: **4 ahead / 0 behind**, exactly four 114O files.
- #753 → #756: **6 ahead / 0 behind**, exactly six 114Q files.
- #756 → #760 execution-plan head: **6 ahead / 0 behind**, exactly six 114R files.

No child contains stale-parent ancestry or unrelated repository deltas at this checkpoint.

## Trust invariants preserved end to end

- exact durable `patch_program_job_id` is preserved from persisted execution through manifest, review records, owner request, and execution plan;
- persisted patch evidence must match the canonical assignment input checksum derived from durable program/job state;
- only the isolated patch role receives `workspace_write`;
- caller-supplied patch receipts cannot establish proposal provenance;
- persisted validation evidence remains bound to completed supervisor records and approved worker policy digests;
- operational and security reviews must be durable, approved, exact-manifest-bound, and from distinct reviewers;
- every durable review read re-resolves the exact persisted patch execution and checks repository, branch, base commit, output checksum, and producer identity;
- owner authorization is short-lived and bound to the exact request digest;
- owner signature verification uses public Ed25519 material only, supports explicit rotation/revocation, and preserves case-sensitive signature envelopes;
- the plan re-derives the request from current durable evidence and re-verifies the owner grant at plan time;
- planned operations must be dependency-closed and canonical;
- no layer silently broadens authority.

## Permanent non-authorities through 114R

No current layer performs or authorizes merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

114R is **plan-only**. It does not execute branch creation, commit creation, push, or pull-request creation. Implementing those external side effects is BUILD-BRAIN-114S and is a separate governance boundary requiring an explicit owner decision.

## Validation state

Each current-parent PR includes focused tests, compilation/lint contracts, static authority-boundary checks, diff hygiene, and dedicated read-only GitHub Actions validation.

Canonical incident #481 remains the blocking validation dependency. The latest 114R-R2 run checked here was Actions run `31292382538`, job `93191659361`; GitHub returned `steps=null`, so checkout and all code validation steps never executed. The strengthened 114M-R1 root likewise has BUILD-BRAIN-114M run `31291499636`, job `93189375746`, with `steps=null`. A separate zero-dependency one-step `echo` diagnostic previously reproduced the same behavior.

These are infrastructure observations only and provide no compile, Ruff, pytest, or diff-hygiene verdict. No current-parent autonomy PR should be marked review-ready or merged until exact unchanged heads obtain executable CI and pass.

## Recovery sequence

When hosted runner allocation resumes:

1. validate #696 exact head;
2. validate #747 exact head;
3. validate #749 exact head;
4. validate #753 exact head;
5. validate #756 exact head;
6. validate #760 exact head;
7. fix actual executable failures before advancing;
8. only after the entire chain is green consider normal merge review in dependency order.

BUILD-BRAIN-114S remains out of scope until an explicit governance decision authorizes development of real branch/commit/push/open-PR side effects.
