# CI and authority hygiene checkpoint — 2026-08-08 20:38 PT

## Purpose

Record validation-independent repository cleanup completed while canonical private-repository GitHub Actions remains unable to start workflow steps. This checkpoint supplements `RS-15-VALIDATION-UPDATE-2026-08-08.md` and canonical infrastructure incident #481.

## Natural recovery check

No blind RS-15 retry was issued.

The newest independently created private backend head inspected was BUILD-BRAIN-114Q-R3 PR #766, head `e62f6004b4abb9449f91e3fa67d3d035c1b754ec`.

Its dedicated BUILD-BRAIN-114Q run `31292752980` created job `93192665401`, which completed `failure` with `steps=null`. The same head also produced pre-step failures in Python Runtime Contract, BUILD-BRAIN-114O, CALYX Workflow Governance, and CALYX-AGENT-003. Therefore private hosted-runner execution had not recovered at this checkpoint.

The current 114N parent PR #762 likewise has dedicated run `31292536356` / job `93192073265` with `steps=null`. These are infrastructure results only: no checkout, compile, lint, test, or diff-hygiene step executed.

## Current-main trust authority

A current-main trust chain now exists:

`#761 BUILD-BRAIN-114M-R2 -> #762 BUILD-BRAIN-114N-R3 -> #763 BUILD-BRAIN-114P-R3 -> #765 BUILD-BRAIN-114O-R3 -> #766 BUILD-BRAIN-114Q-R3`

This chain is the active authority for these milestones while executable validation remains blocked.

## Supersession cleanup completed

Closed unmerged:

- #747 BUILD-BRAIN-114N-R2, superseded by current-main #762;
- #749 BUILD-BRAIN-114P-R2, superseded by current-main #763;
- #750 BUILD-BRAIN-114O-R2, superseded by current-main #765;
- #764 alternate BUILD-BRAIN-114N-R3, closed as redundant because direct diff inspection showed the same six-file runtime/test/workflow capability as #762 while the live downstream chain is already based on #762.

Historical branches remain available as provenance. Closure does not authorize merge, deployment, Git/GitHub mutation runtime, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation.

## Supersession rule

Close a stale draft without executable CI only when repository evidence establishes an unambiguous replacement authority or a functionally duplicate branch whose downstream dependency chain already selects one parent.

Do not close fallback/older drafts when the replacement itself explicitly conditions supersession on a future green executable validation gate.

## RS-15 boundary

RS-15 remains frozen at runtime head `7ac7fc430ec1518b91e8c8d4eca3e43ddd597238`, draft/unmerged/non-production. No RS-16 expansion is authorized before a private-repository workflow materializes real steps and the unchanged RS-15 formatting, lint, Vitest, and production-build gate executes successfully.

## Recovery trigger

The first private-repository workflow job with a non-empty materialized step list is the recovery signal. At that point, validate unchanged RS-15 first, fix real project-stage failures before expansion, and only then consider review-ready promotion.