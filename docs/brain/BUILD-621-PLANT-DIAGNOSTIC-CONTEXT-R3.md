# BUILD-621-R3 — Plant Diagnostic Context on Canonical BUILD-620

Status: IMPLEMENTED; pending exact-head validation and review.

Parent: canonical BUILD-620-R4 / PR #810, merged to `main` as `27f5f912d0ebc09d0fa4ee996b0e07b56e6900c7`.

Historical source: BUILD-621-R2 / PR #790 at `7f5bfd4da5cc9dbcda81e3d489a9fcee4475ba26` is superseded as integration authority because it depended on stale BUILD-620-R2 ancestry. R3 reconstructs the intended diagnostic composer directly on canonical main.

Delivered:
- protected `POST /brain/diagnostic-context`;
- `canonical_reasoning` produced exclusively by the canonical scoped Reasoning Map;
- `local_observation_context` read from governed local Candidate Knowledge observations;
- explicit separation of canonical mechanisms from local observations;
- applicable / out-of-scope / indeterminate canonical path counts remain visible;
- local observations never imply a canonical mechanism;
- similarity remains explicitly noncausal;
- composer is read-only and has no scientific publication authority.

Scientific and governance boundaries:
- no Candidate Knowledge promotion;
- no scientific publication;
- no canonical or production Knowledge Graph mutation;
- no production DB migration or mutation;
- no taxonomy activation;
- no deployment;
- no scientific review decision;
- no competing publication adapter.

Release gate:
1. exact current head must remain synchronized with canonical main;
2. dedicated BUILD-621 validation must pass;
3. BUILD-620/619 prerequisite regressions must pass;
4. Workflow Governance, Canonical Brain, Calyx Brain Integration, Brain E2E, Candidate Knowledge/publication-control validation, lint, formatting, compile/static checks must pass where applicable;
5. review threads and requested-change reviews must be clear;
6. merge only using the exact validated head.

Brain status vocabulary: IMPLEMENTED -> EXACT-HEAD VALIDATED -> READY FOR REVIEW -> MERGED TO CANONICAL MAIN.
