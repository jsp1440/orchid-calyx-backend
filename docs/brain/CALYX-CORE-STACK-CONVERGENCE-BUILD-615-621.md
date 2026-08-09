# CALYX Core Stack Convergence — BUILD-615 through BUILD-621

Final status: **MERGED TO CANONICAL MAIN** through BUILD-621-R3.

This record is the canonical convergence ledger for the dependency-ordered BUILD-615→621 integration cycle completed on 2026-08-09. Historical stacked lineages remain audit/source material only and are not integration authority.

| Build | Canonical PR | Exact merged head | Canonical merge SHA | Disposition |
|---|---:|---|---|---|
| BUILD-615 | #733 | `4b91d9db50bd12bd12b359beb341e47ed2ea13e5` | `efdd0b02295d4fccf0628ec116552ac41dc76d5c` | MERGED TO CANONICAL MAIN |
| BUILD-616R | #796 | `745006ee3f783c1bea76c2766e4b37ca6e920b25` | `46112f1bdfe0ccf724616b9c7925a8652e48c9e2` | MERGED TO CANONICAL MAIN |
| BUILD-617R3 | #797 | `54063c08f8efb0ba429272afbb6d9090910a78d0` | `c89826e808f09555c4662ec03e61d89bdf1f4ebb` | MERGED TO CANONICAL MAIN |
| BUILD-616R corrective hardening | #795 | `8cd69c0b6d6ea315d3b7c601dac9607b75aa5c60` | `677a506ab61338e9d9a13ece67d972c2c22a044c` | MERGED TO CANONICAL MAIN |
| BUILD-618-R4 | #803 | `7997b3f51b857c586cd1989353d48f8a2db72746` | `6daef86a171f962604cc84f72ec26c19169bbf57` | MERGED TO CANONICAL MAIN |
| BUILD-619-R3 | #805 | `df0f47172d5ae298acab9525f52ceb14588b3c54` | `6aff70a2b2fe75fd0be4311431ffd04a3c2df3b1` | MERGED TO CANONICAL MAIN |
| BUILD-620-R4 | #810 | `74633b9d0cdf4ca0c938054eff47cb1379968286` | `27f5f912d0ebc09d0fa4ee996b0e07b56e6900c7` | MERGED TO CANONICAL MAIN |
| BUILD-621-R3 | #812 | `12882d5366a971682d1865e97e90d2b282f2114e` | `a54a189d30384bda1c1ece00e653f6b41c486a3f` | MERGED TO CANONICAL MAIN |

## Exact-head validation at final frontier

BUILD-620-R4 exact head `74633b9d0cdf4ca0c938054eff47cb1379968286` passed all 11 applicable PR-triggered workflows, including BUILD-620 Local Observation Validation, Workflow Governance, Candidate Handoff, BUILD-615, BUILD-616R, BUILD-617R3, BUILD-088E, Platform Routes, Parallel Platform, Calyx Brain Integration, and Brain E2E. Review threads were clear and the branch was synchronized with canonical main immediately before merge.

BUILD-621-R3 exact head `12882d5366a971682d1865e97e90d2b282f2114e` passed all 13 applicable PR-triggered workflows: BUILD-621 Plant Diagnostic Context Validation, BUILD-619 Reasoning Scope Validation, Workflow Governance, Canonical Brain, Calyx Brain Integration, Brain E2E, BUILD-088E, CALYX-CORE-REBASE-003, CALYX-AGENT-001/003/004, CALYX-JOURNALISM-MVP, and CALYX-BRAIN-EDU-DESIGN-001. Its dedicated workflow passed compile, Ruff lint, Ruff formatting, diagnostic regressions plus BUILD-620/619 regressions, route verification, and hygiene. Review submissions and inline review threads were empty. The branch was 0 behind canonical main immediately before merge.

## Scientific / knowledge contract impact

- Candidate Knowledge duplicate identity remains governed by the canonical Candidate Knowledge contract; convergence did not weaken duplicate detection.
- Local cultivation observations remain `CULTIVATION_OBSERVATION`, local-only, review-required, `published=false`, non-generalizable, and noncausal.
- Provenance remains canonical; no alternate provenance representation was introduced.
- Canonical reasoning remains separate from local observation context.
- Applicability remains explicit as applicable / out-of-scope / indeterminate; unknown or partial scope is not silently generalized.
- Co-occurrence, similarity, and local observation are not rewritten as causal mechanism.
- Publication planning remains fail-closed and read-only, with no competing publication execution adapter.
- `POST /brain/diagnostic-context` is read-only and keeps `canonical_reasoning` and `local_observation_context` distinct.

## Governance impact

No scientific publication, automatic Candidate Knowledge promotion, taxonomy activation, deployment, production database mutation, production Knowledge Graph mutation, scientific review decision, or production write authority occurred in this convergence cycle.

## Superseded lineages

Historical BUILD-618-R2 #787, BUILD-618-R3 #800, BUILD-620-R2 #789, BUILD-620-R3 #807, and BUILD-621-R2 #790 are **SUPERSEDED** as integration authority. Their validated results remain audit evidence only where useful.

## Final dependency disposition

The requested BUILD-615→621 dependency stack is fully canonical. The next Core surface may now be selected independently, subject to the existing governance boundaries and fresh exact-head validation.
