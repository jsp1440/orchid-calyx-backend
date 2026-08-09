# BUILD-BRAIN-114P — Durable proposal-review authorization registry

## Status

VALIDATED on canonical `main` after BUILD-BRAIN-114M-R3 and BUILD-BRAIN-114N merged. PR #782 was reconstructed onto merged 114N, retargeted to `main`, and reduced to the six intended additive 114P files.

## Objective

Persist governed repository-proposal review evidence durably and verify it on every read without granting Calyx Git/GitHub mutation authority.

## Current lineage

Canonical trust chain: `#772 BUILD-BRAIN-114M-R3 → #781 BUILD-BRAIN-114N → #782 BUILD-BRAIN-114P`.

BUILD-BRAIN-114M supplies canonical assignment inputs, durable execution identity, exact governed patch input/output agreement, manifest v2 and crash-recoverable isolated workspace mutation. BUILD-BRAIN-114N adds canonical manifest revalidation, requester/producer separation, role-qualified operational/security review semantics, immutable per-class review evidence, and distinct-reviewer completion requirements.

Historical 114P branches rooted in older 114N heads are source material only. The current #782 branch has canonical `main` as merge base and is behind 0.

## Durable trust contract

`DurableProposalAuthorizationStore.record_review()` is the governed write path. It invokes the hardened 114N builder, re-resolves the exact durable patch through `PersistedPatchExecutionService`, verifies manifest v2 and patch-job identity, enforces reviewer separation and roles, and only then persists the decision.

Every durable read verifies schema, payload digest, row digest, row identity, review class, reviewer-role membership, reviewer separation from requester and patch producer, canonical reviewer-role representation, and current durable patch evidence. ORM reads use `populate_existing`, and patch-evidence verification expires cached session state first so another transaction cannot be hidden by SQLAlchemy identity-map state.

## Persistence

The forward-only migration creates the decision table, unique manifest/class pair, unique authorization digest, and allowed review-class check. Database immutability is enforced by a PostgreSQL `BEFORE UPDATE OR DELETE` trigger that raises SQLSTATE `55000`; review rows are INSERT-only at the database boundary.

The migration is included in source control but is not applied to production by this implementation slice.

## Failure-first record

FACT — Hosted runners are executing normally. No current 114P failure is attributable to GitHub hosted-runner infrastructure.

INTEGRATION/ANCESTRY — #782 originally targeted an obsolete pre-merge 114N feature branch and was 74 commits behind canonical main. It was reconstructed with an auditable two-parent commit on merged 114N and retargeted to `main`; comparison then showed behind 0 and exactly six 114P files.

P1 DATABASE — Review found that uniqueness alone did not make durable review rows immutable because the database role could still UPDATE or DELETE them. The migration now installs a database trigger rejecting both operations.

P1 CODE — Review found that a digest-consistent row could bypass 114N reviewer invariants during decoding. Durable reads now reapply review-class membership, reviewer separation, and canonical role invariants before materialization.

P2 DATABASE/SESSION FRESHNESS — Review found that SQLAlchemy identity-map state could hide patch evidence changed by another transaction. Durable reads now refresh decision rows and expire session state before persisted patch verification.

DEPENDENCY/TEST CONTRACT — The old 114P fixture used `validations=[]`, which is intentionally invalid under merged hardened 114N. The fixture now supplies a canonical validation covering the exact proposed postimage; no production gate was weakened.

## Validation

Exact implementation/workflow head `f684dfcbc43d8cbea0163b607e101a5b45241106` passed all applicable suites:

- BUILD-BRAIN-114P Durable Proposal Authorization Validation `31327069175` — success. PostgreSQL 16 service initialized; compile, Ruff lint/format, focused durable/114N regressions, migration contract, real PostgreSQL immutable-row UPDATE/DELETE rejection, static authority checks, and diff hygiene all passed.
- CALYX-AGENT-003 Validation `31327069179` — success.
- BUILD-088E Validation `31327069197` — success.
- CALYX Workflow Governance Audit `31327069255` — success.

Focused adversarial regressions prove a second SQLAlchemy session's patch-evidence tamper is observed by the original store and that digest-consistent rows cannot bypass requester/reviewer separation or matching review-role requirements.

## Governance boundary

No Git command, branch creation, commit, push, pull-request creation, merge/auto-merge, deployment, scientific publication, taxonomy activation, production database migration, or production Knowledge Graph mutation is authorized by this slice. The migration file is integrated code only; production application remains a separate governance action.

## Next dependency

BUILD-BRAIN-114O may be reconstructed only after this exact documentation head revalidates and #782 is merged. Actual Git/GitHub side-effect transport remains a separate governance boundary.
