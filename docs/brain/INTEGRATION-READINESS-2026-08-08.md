# Orchid Continuum Integration Readiness — 2026-08-08

## Purpose

Record the current integration bottleneck after live GitHub inspection, distinguish executable failures from dependency-stack delay, and define the next release order without crossing protected merge/deployment/scientific-governance boundaries.

## Current finding

The dominant bottleneck is **integration debt / stacked dependency depth**, not a broad GitHub Actions failure condition.

Recent exact-head workflow evidence is green for the critical Research Station analysis chain:

- CALYX-448 Literature Acquisition: current head validation green.
- CALYX-617 Scientific Analysis: current head validation green, including Literature and Research Station regressions.
- CALYX-631 Registered Dataset Rows: current head validation green, including Scientific Analysis, Research Station, Literature, governance, supervised-pilot, and autonomy/deployment workflows.

The repository workflow-governance auditor previously reached zero routine owner bottlenecks while retaining the legitimate destructive production-migration gate.

## Critical dependency chain

The highest-value consolidation chain is:

`main -> CALYX-448 (#601) -> CALYX-453 (#606) -> CALYX-617 (#618) -> CALYX-631 (#633)`

Frontend Research Station work depends on that backend chain.

### Important drift finding

At this audit, CALYX-448 remains mergeable but its branch has materially diverged from current `main` (7 commits ahead / 69 commits behind). This means green branch-local CI is necessary but not sufficient evidence for release. Before any owner-authorized merge, the exact release candidate must be refreshed against current `main` and revalidated.

## Other stacked integration chains

- Taxonomy: CALYX-461 (#598) -> occurrence/media/pollinator dependent slices.
- Matrix/Vision: CALYX-449 (#602) -> CALYX-450 (#603).
- Conservatory/OASIS: CALYX-451 (#604) -> CALYX-452 (#605).
- Literature-dependent science: mycorrhiza (#615), conservation (#616).
- Research Station-dependent applications: University (#611), funding intelligence (#613).
- Scientific reasoning: BUILD-614 (#628) extends the controlled causal vocabulary.

These should not be expanded merely to increase build count while foundational branches remain unintegrated.

## Cleanup completed in this audit

PR #631, a Copilot Ruff-formatting fix, had become a zero-diff PR because the correction is already present in the CALYX-617 base. It was closed as superseded. No code was discarded.

## Release discipline

For each foundational chain:

1. Refresh the lowest dependency against current `main`.
2. Run exact-head compile/lint/focused tests plus relevant regressions.
3. Fix failures before moving upward.
4. Revalidate the next dependent branch against the refreshed parent.
5. Preserve provenance and Brain records.
6. Do not merge, deploy, activate taxonomy, run destructive production migrations, publish scientific conclusions, or mutate the production Knowledge Graph where the governing issue/PR explicitly reserves that authority.

## Next highest-priority action

Refresh and revalidate CALYX-448 against current `main`, because it is the root dependency for Research Station, Scientific Analysis, registered dataset transport, mycorrhizal evidence, and conservation evidence. Once its exact current-main candidate is green, the same procedure should proceed upward through #606, #618, and #633.

## Status

- Broad CI-collapse hypothesis: **not supported by current evidence**.
- Integration-stack bottleneck: **confirmed**.
- Redundant PR cleanup: **completed (#631)**.
- Critical exact-head workflows: **green before current-main refresh**.
- Protected release/merge boundaries: **preserved**.
