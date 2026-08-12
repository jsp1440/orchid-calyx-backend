# CALYX PR Portfolio Consolidation Update — 2026-08-12

## Active backend integration set

The active backend PR queue has been reduced again, from six to five. PR #878 (protected live Speak acceptance harness) was closed without merge because it is validation-only and its three-file implementation remains preserved in Git history for selective reconstruction into the active Speak integration authority when executable CI is restored.

The five active backend PRs are now:

- #900 — durable mission queue / validator-driven worker;
- #897 — runtime vs migration database-target equivalence;
- #896 — canonical Lexicon direct-entry contract;
- #894 — Matrix session optimistic concurrency;
- #893 — integrated grounded Speak/Matrix/provider-readiness workspace.

## Integration authority

#893 is the active integration authority for Speak/Matrix/provider-readiness behavior. Historical or validation-only Speak branches are source material, not independent merge targets.

#900 is the active orchestration/autonomy integration authority and is tagged `integration-priority`.

## Runner incident evidence

The latest CALYX-AUTO-001 job for run 31567534704 / job 94022368279 completed with `steps: null`; the dedicated step endpoint returns an empty step list. Therefore no checkout, install, test, compile, Ruff, migration validation, or governance assertion executed. Do not infer code failure from that run and do not blind-rerun it.

## Governance

No merge, deployment, production migration, taxonomy activation, scientific publication, production Knowledge Graph mutation, spending action, credential change, force-push, or branch deletion is authorized or performed by this consolidation work.
