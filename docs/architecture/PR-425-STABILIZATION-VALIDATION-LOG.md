# PR #425 Stabilization Validation Log

## Purpose

Record the evidence-driven stabilization of the canonical Brain integration umbrella and its dependency-ordered review slices.

## Umbrella disposition

- PR #425 remains draft.
- PR #425 must not be merged directly.
- Feature expansion remains paused while core slices are validated.
- Decomposition tracker: issue #486.
- The former repository-wide CI blocker, issue #481, is closed because fresh PR events proved GitHub Actions is operational.

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
2. Direct `pytest` invocation failed to resolve the repository `app` package; workflow changed to `python -m pytest` and `python -m ruff`.
3. Behavioral tests showed that the query `FigureLabs glossary` ranked a decision record above the architecture record.
4. Search ranking was corrected to prefer architecture records when relevance is otherwise tied.
5. A final Ruff import-group correction was applied to `registry.py`.

Current state:

- draft
- unmerged
- latest validation run pending for the most recent formatting correction

### PR #488 — Slice 2: Governance and Persistence

Scope:

- persistence interface and deterministic JSON repository
- Intent Graph and governance coverage
- executable Constitution and admission API
- Mission Control Brain status

Validation findings and corrections:

1. Broader CALYX Agent, Journalism, Brain Integration, Education Design, and End-to-End checks passed.
2. Focused Canonical Brain lint identified a sorted `__all__` requirement and three multiline import-format corrections.
3. The branch now contains those deterministic formatting corrections.
4. A fresh focused validation run is required for the current head.

Current state:

- draft
- stacked on Slice 1
- unmerged
- validation pending for current head

### PR #489 — Slice 3: Governed Orchestration

Scope:

- governed build queue
- deterministic agent assignment
- dry-run executor boundary
- leases, heartbeats, timeouts, recovery, cancellation, and receipts

Current state:

- draft
- stacked on Slice 2
- unmerged
- workflow invocation standardized to the active Python environment
- independent failure inspection remains after Slices 1 and 2 stabilize

## CI conclusion

GitHub Actions is enabled and functional. The absence of statuses on the umbrella branch did not indicate a repository-wide administrative policy failure. Fresh stacked PRs produced workflow runs and exposed real, actionable failures. Issue #481 was therefore closed after evidence disproved its original diagnosis.

## Governance boundary

No slice may merge until its latest head has compile, Ruff, and focused pytest evidence. No auto-merge, deployment, publication, production database migration, external delivery, or production Knowledge Graph mutation is authorized.

## Standing lesson

Large integration branches can obscure validation state. Dependency-ordered slices improve failure isolation, reviewability, rollback, and truthful reporting. Build count is not completion; validated integration is completion.
