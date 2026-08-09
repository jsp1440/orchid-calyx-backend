# BUILD-BRAIN-114M → 114R current-parent handoff

## Authoritative chain

The autonomy proposal trust chain is reconstructed on the exact current R5 dependency path. Superseded R1/R2/R3/R4 branches remain historical source material only.

Current sequence:

1. **#772 — BUILD-BRAIN-114M-R3** — durable persisted patch provenance and manifest-v2 trust root.
2. **#781 — BUILD-BRAIN-114N-R6** — exact-manifest operational/security review evidence.
3. **#782 — BUILD-BRAIN-114P-R5** — durable tamper-evident review registry.
4. **#783 — BUILD-BRAIN-114O-R5** — durable-reviewed owner authorization request v2.
5. **#784 — BUILD-BRAIN-114Q-R5** — public-key-only Ed25519 owner-grant verification; exact validated documentation head `dd54600a48eb6f9be4e4475c41b1d31ce4dee6a6`.
6. **#785 — BUILD-BRAIN-114R-R5** — deterministic authorization-bound execution plan v2 on #784, with no Git/GitHub side effects; implementation head `8ec022e5aa93002f9a22a2bc5582ace6d3f25aa1` validated green before the documentation checkpoint.

Historical #760, #767, #768 and earlier 114R predecessors are not integration paths.

## Trust invariants propagated end to end

- exact durable `patch_program_job_id` from patch execution through manifest, review records, owner request, owner verification, and plan;
- canonical assignment-input checksum reconstructed from durable program/job state;
- caller-supplied patch receipts cannot establish proposal provenance;
- operational/security reviews remain durable, exact-manifest-bound, independently reviewed, and reverified on read;
- owner authorization is short-lived, request-digest-bound, and independently re-derived at plan time;
- Ed25519 verification uses public material only with explicit rotation/revocation and case-sensitive signature envelopes;
- the planner re-derives the request from current durable evidence and re-verifies the owner grant;
- planned operations must be dependency-closed and canonical;
- no layer silently broadens authority.

## Permanent non-authorities through 114R

No layer in the R5 chain performs or authorizes merge/auto-merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

114R is plan-only. It executes no branch creation, commit creation, push, or pull-request creation. BUILD-BRAIN-114S remains a separate explicit owner-governance boundary.

## Validation state

Executable GitHub-hosted validation is functioning on this private repository.

BUILD-BRAIN-114Q-R5 exact documentation head `dd54600a48eb6f9be4e4475c41b1d31ce4dee6a6` received successful dedicated 114Q validation, Python runtime validation, CALYX-AGENT-003 validation, Workflow Governance validation, and successful 114O focused execution before 114R was rooted on it.

BUILD-BRAIN-114R-R5 implementation head `8ec022e5aa93002f9a22a2bc5582ace6d3f25aa1` then received:

- BUILD-BRAIN-114R validation run `31297652976` — success, including compile, Ruff lint/format, focused regressions, v2 provenance/non-mutation assertions, and diff hygiene;
- CALYX Workflow Governance Audit run `31297652972` — success;
- CALYX-AGENT-003 Validation run `31297652970` — success.

The current documentation checkpoint changes no runtime behavior and must itself receive applicable read-only validation. Once it is green, 114R is complete and autonomous expansion stops.

## Governance boundary

The next code-bearing step would be BUILD-BRAIN-114S: a real proposal mutation executor capable of branch/commit/push/open-PR side effects. That is not authorized by this handoff and requires an explicit owner governance decision before implementation.
