# CI and authority hygiene checkpoint — 2026-08-08

## Purpose

Record validation-independent repository cleanup completed while canonical private-repository GitHub Actions remains unable to start workflow steps. This checkpoint supplements `RS-15-VALIDATION-UPDATE-2026-08-08.md` and canonical infrastructure incident #481.

## Natural recovery status

No blind RS-15 retry was issued.

The current active BUILD-BRAIN trust root is PR #772 (`BUILD-BRAIN-114M-R3`), rebuilt directly on current backend `main` after #761 drifted behind. Its exact audited head is `06f3bc3a98d579af62906dd463609968b7bf23f2`.

The dedicated BUILD-BRAIN-114M workflow on that exact head is run `31293419153`, job `93194537448`. The job completed `failure` with `steps=null`; no checkout, compile, Ruff, pytest, or diff-hygiene step executed. The same head also had pre-step failures in BUILD-BRAIN-108-113A, BUILD-BRAIN-114I, BUILD-BRAIN-114A, BUILD-088E, CALYX Workflow Governance, and CALYX-AGENT-003.

OCU-SCI-009N current head `c4971efde2288440381c5061c5595886bc7d127d` likewise triggered OCU University Migration Runner run `31293733300`, job `93195318464`, with `steps=null`; Durable Foundation `31293733266`, BUILD-088E `31293733293`, and Workflow Governance `31293733296` failed before step 1 on the same head.

Therefore private hosted-runner execution has not recovered. These are infrastructure results only and are not code pass/fail evidence.

## Current BUILD-BRAIN authority

The previously recorded #761 -> #762 -> #763 -> #765 -> #766 chain is no longer authoritative because `main` advanced and the root had to be reconstructed again.

Current authority is intentionally reduced to one integration root:

`#772 BUILD-BRAIN-114M-R3`

There is **no active authoritative 114N/P/O/Q/R descendant yet**. Rebuild order must restart from the exact #772 head:

1. BUILD-BRAIN-114N directly on #772;
2. BUILD-BRAIN-114P directly on that new 114N;
3. BUILD-BRAIN-114O directly on that new 114P;
4. BUILD-BRAIN-114Q directly on that new 114O;
5. BUILD-BRAIN-114R directly on that new 114Q.

Do not skip levels or reuse a descendant whose parent was closed/non-mergeable.

## Supersession cleanup completed

Earlier cleanup closed #747, #749, #750 and duplicate #764. During this checkpoint additional ancestry drift was detected and retired.

Closed unmerged / confirmed closed unmerged:

- #761 BUILD-BRAIN-114M-R2 — superseded by current-main #772;
- #762 BUILD-BRAIN-114N-R3 — superseded after the trust root changed;
- #763 BUILD-BRAIN-114P-R3 — superseded after its 114N parent was retired;
- #765 BUILD-BRAIN-114O-R3 — closed because it depended on retired #763/#762/#761 ancestry;
- #766 BUILD-BRAIN-114Q-R3 — closed because it depended on retired O/P/N/M ancestry;
- #767 BUILD-BRAIN-114R-R3 — closed because it depended on retired Q/O/P/N/M ancestry;
- #771 BUILD-BRAIN-114N-R4 — closed after retargeting to #772 proved non-mergeable; the 114N capability must be rebuilt directly on exact #772;
- #773 BUILD-BRAIN-114P-R4 — closed because its parent #771 is closed/non-mergeable;
- #775 BUILD-BRAIN-114O-R4 — closed immediately because it was created on closed #773 and therefore propagated invalid ancestry.

Historical branches remain available as provenance/source material. Closure does not authorize merge, deployment, Git/GitHub mutation runtime, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

## #772 trust-root audit

The #772 PR changes exactly nine intended files:

- `.github/workflows/build-brain-114m-git-proposal-manifest.yml`;
- `app/calyx_orchestrator/assignment_factory.py`;
- `app/calyx_orchestrator/execution_bridge.py`;
- `app/calyx_orchestrator/git_proposal_manifest.py`;
- `app/calyx_orchestrator/persisted_patch_execution.py`;
- `docs/brain/BUILD-BRAIN-114M-GIT-PROPOSAL-MANIFEST.md`;
- `tests/test_calyx_assignment_capabilities_114m_r1.py`;
- `tests/test_calyx_git_proposal_manifest.py`;
- `tests/test_calyx_persisted_patch_execution.py`.

Static trust-boundary review completed during this checkpoint:

- `workspace_write` is granted only when role is `isolated_workspace_patcher` **and** durable `mutating` intent is true;
- non-patch roles receive only safe assignment capabilities;
- assignment input checksums are reconstructed from durable program/job state;
- persisted execution receipts bind assignment ID, program ID, job key, isolated-patch executor identity, input checksum, output checksum, repository, branch, execution mode, isolation/disposable state, and exact governed patch input/output agreement;
- proposal manifest v2 removes caller-supplied `patch_receipt` authority and resolves only a persisted patch job;
- caller-provided supervisor validation is rechecked against persisted supervisor evidence;
- no import cycle was introduced between `assignment_factory` and `isolated_patch_executor`;
- the current runtime audit found no additional defect that justified a speculative code change before executable CI.

The exact `main...head` comparison is 10 commits ahead / 0 behind and contains only the nine paths listed above.

The focused workflow includes compile, Ruff check/format, three focused test files, static non-mutation assertions, and diff hygiene, but none can currently run because hosted jobs stop before step 1.

## OCU-SCI-009N migration-runner authority

Current authority:

- #777 `OCU-SCI-009N v4: guarded migration refresh on latest main`, based directly on backend `main` commit `6dc9466442e7d5172269a451691b3e9bf5e0b5c7`;
- exact current runtime/test head `c4971efde2288440381c5061c5595886bc7d127d`;
- prior #748 v3 is closed unmerged as superseded.

### Concurrency/idempotency defect found and fixed

Static safety review found that the initial v4 runner only checked `schema_already_valid` before acquiring its transaction-scoped advisory lock. Two legitimate operators could both see an invalid schema and plan an apply. Operator A could acquire the lock and complete the migration; Operator B would then acquire the lock but, without re-reading schema state, would replay the idempotent SQL and report `mutations_performed=true`. The SQL uses `IF NOT EXISTS`, so this was not destructive, but it violated the runner's truthful idempotent no-op contract and performed unnecessary database statements.

Correction on #777:

- after acquiring `pg_advisory_xact_lock`, the runner re-reads durable schema state inside the same transaction;
- if schema is already valid at that point, it executes no migration SQL and returns `already_valid_noop_after_lock` with `mutations_performed=false`;
- otherwise it executes the exact confirmed migration bytes, verifies the durable schema before transaction completion, and returns `applied_and_verified` only after successful verification;
- focused regression `test_concurrent_winner_becomes_noop_after_advisory_lock` asserts the advisory lock is acquired and the migration SQL body is not executed when another operator won the race;
- the ordinary apply-path mock now explicitly models locked-state invalid followed by post-apply valid schema.

The migration remains dry-run by default and still requires exact migration SHA-256 confirmation, exact sanitized database-target confirmation, migration-stage preflight, bounded connect/lock/statement timeouts, transactional advisory locking, same-transaction verification, and rollback on failed verification.

Exact-head validation is still infrastructure-blocked: run `31293733300`, job `93195318464`, `steps=null`. No PostgreSQL test or application step executed. PR #777 remains draft/unmerged and no production migration has been applied.

#777 must not merge or apply a production migration until PostgreSQL apply/verification/rollback tests (including the post-lock no-op race), migration invariants, Durable Foundation, BUILD-088E, review audit, and final current-main comparison all execute and pass.

## Supersession rule

Close a stale draft without executable CI when repository evidence establishes either:

- an unambiguous replacement authority on a newer trust root; or
- a descendant whose parent has been proven invalid/non-mergeable and therefore cannot remain an integration authority; or
- a functionally duplicate branch whose downstream chain already selects one parent.

Do not close unrelated fallback implementations merely because they are old when their replacement explicitly conditions supersession on a future executable green gate.

## RS-15 boundary

RS-15 remains frozen at runtime head `7ac7fc430ec1518b91e8c8d4eca3e43ddd597238`, draft/unmerged/non-production. No RS-16 expansion is authorized before a private-repository workflow materializes real steps and the unchanged RS-15 formatting, lint, Vitest, and production-build gate executes successfully.

## Recovery trigger

The first private-repository workflow job with a non-empty materialized step list is the recovery signal. At that point:

1. validate unchanged RS-15 first;
2. validate exact #772 before rebuilding downstream BUILD-BRAIN authorization layers;
3. validate exact #777 before any migration-runner promotion or production action;
4. fix any real project-stage failures before expansion;
5. only then consider review-ready promotion or rebuilding the 114N -> 114R chain.