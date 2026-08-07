# PR #425 Stabilization Validation Log

## Purpose

Record the evidence-driven stabilization of the canonical Brain integration umbrella and its dependency-ordered review slices.

## Umbrella disposition

- PR #425 remains draft.
- PR #425 must not be merged directly.
- Feature expansion remains paused while core slices are validated.
- Decomposition tracker: issue #486.
- Former issue #481 is closed: fresh pull-request events proved GitHub Actions is operational.

## Stacked review slices

### PR #487 — Slice 1: Canonical Brain Core

Scope:

- object and relationship contracts
- registry, search, traversal, and deterministic snapshots
- canonical fixture
- read-only API
- atomic build-capture handoff

Validation findings and corrections:

1. Ruff identified an unsorted import and unnecessary `dict()` constructor in registry tests.
2. Direct `pytest` invocation failed to resolve the repository `app` package; workflows were changed to `python -m pytest` and `python -m ruff`.
3. Behavioral tests showed that `FigureLabs glossary` ranked a decision record above the architecture record.
4. Search ranking was corrected to prefer architecture records when relevance is otherwise tied.
5. Import grouping was normalized.
6. Exact connector-backed reconstruction of head `0d5dcb78350cb585096daee3d9e404dd030c587c` passed Python compilation and seven focused tests locally.

Current state:

- draft and unmerged
- mergeable against `main`
- local compile and focused pytest evidence exists
- latest GitHub workflow runs are `action_required` with no jobs; repository-side approval is required before authoritative Ruff and pytest execution

Reviewer next action:

- approve the pending GitHub Actions workflows for PR #487
- do not merge until the approved run completes successfully

### PR #488 — Slice 2: Governance and Persistence

Scope:

- persistence interface and deterministic JSON repository
- Intent Graph and governance coverage
- executable Constitution and admission API
- Mission Control Brain status

Validation findings and corrections:

1. Broader CALYX Agent, Journalism, Brain Integration, Education Design, and End-to-End checks passed on an earlier head.
2. Focused Canonical Brain lint identified sorted-export and multiline-import requirements; the current branch contains those formatting corrections.
3. The branch contains architecture-first search behavior and updated Mission Control fixture assertions.
4. Direct comparison with repaired Slice 1 shows Slice 2 is 26 commits ahead and 7 commits behind, with merge base `03243574afd053104b7edb9ad8c8a605cfc809a7`.
5. Connector inspection confirmed that no safe merge/rebase operation is available; force-rewriting the draft branch was deliberately rejected.

Current state:

- draft and unmerged
- temporarily non-mergeable because the stacked base advanced during Slice 1 repairs
- preserve the current branch as evidence
- reconcile by a reviewed restack or clean replacement branch after Slice 1 CI approval

Reviewer next action:

- complete Slice 1 workflow approval first
- then restack Slice 2 onto the accepted Slice 1 head and rerun focused validation

### PR #489 — Slice 3: Governed Orchestration

Scope:

- governed build queue
- deterministic agent assignment
- dry-run executor boundary
- leases, heartbeats, timeouts, recovery, cancellation, and receipts

Current state:

- draft and unmerged
- temporarily non-mergeable because Slices 1 and 2 advanced
- workflow invocation standardized to the active Python environment
- preserve the current branch as evidence
- independent validation remains after lower slices are reconciled

Reviewer next action:

- do not restack or validate Slice 3 until Slice 2 has a stable accepted head

## CI conclusion

GitHub Actions is enabled and functional. Fresh stacked pull requests produced workflow runs and exposed actionable lint, import-path, and behavioral failures. The newest Slice 1 runs are not code failures: GitHub reports `action_required` and creates no jobs until repository-side approval is granted.

## Governance boundary

No slice may merge until its latest head has compile, Ruff, and focused pytest evidence. The connected API cannot approve an `action_required` workflow and cannot safely merge/rebase one draft branch into another. No force-push, auto-merge, deployment, publication, production database migration, external delivery, or production Knowledge Graph mutation is authorized.

## Standing lesson

Large integration branches can obscure validation state. Dependency-ordered slices improve failure isolation, reviewability, rollback, and truthful reporting. Build count is not completion; validated integration is completion.

## Turn disposition

No further implementation should expand feature scope until PR #487 receives repository-side workflow approval and authoritative CI evidence. The correct next action is administrative approval, followed by Slice 1 CI review and a controlled restack of Slice 2.

## Metadata synchronization

The pull-request conversations are being updated to mirror this record and remove obsolete references to closed issue #481.
