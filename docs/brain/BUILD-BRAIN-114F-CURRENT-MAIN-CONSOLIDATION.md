# BUILD-BRAIN-114F — Current-main autonomy consolidation

## Purpose

Reconcile the validated autonomous-engineering primitives onto the authoritative current `main` lineage without overwriting unrelated newer work.

## Current state

`main` already contains BUILD-BRAIN-114B (read-only repository evidence) and BUILD-BRAIN-114C (bounded isolated-workspace patching). This branch starts from that current-main state and adds BUILD-BRAIN-114D static validation as an incremental integration rather than merging stale stacked history.

## Included in this slice

- current-main registration of `isolated_workspace_static_validator`;
- read-only exact-postimage hash validation;
- Python AST parse/compile checks without repository code execution;
- dedicated focused tests and CI;
- explicit registry reporting of repository-code execution authority;
- current-main Brain documentation.

## Safety

No shell/subprocess execution, network use, credentials, Git commit generation by Calyx, PR generation by Calyx, merge authority, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is enabled.

## Next gate

Require focused CI on this current-main-derived branch. If green, integrate the persisted-input patch→validation orchestration layer from BUILD-BRAIN-114E onto this branch, preserving newer mainline changes and re-running the complete autonomy validation surface.
