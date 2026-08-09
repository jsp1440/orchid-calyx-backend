# BUILD-620-R2 Validation Record

Status: executable-green and ready for review.

Integration base: BUILD-619-R2 / PR #788 (`feature/build-619-reasoning-scope-evaluation-r2`).

Validated code head: `05d289c2390c0e36405fdf41c8e39b95506abca7`.

Scope: Matrix / Conservatory local-observation bridge only. Local observations enter Candidate Knowledge as review-required, unpublished, non-causal `CULTIVATION_OBSERVATION` evidence with bounded `n=1` applicability scope. Protected write/read routes expose submission and longitudinal history.

## Executable validation

Dedicated BUILD-620 workflow run `31322961323` completed successfully. It passed dependency setup, compile, Ruff lint, Ruff formatting, BUILD-620 local-observation regressions, BUILD-619 scoped-reasoning regressions, BUILD-618 causal-scope regressions, protected Matrix route verification, and repository hygiene.

Applicable broad checks on the same exact code head also completed successfully:

- BUILD-615 Mechanistic Candidate Validation — run `31322961305`;
- BUILD-616 Mechanistic Publication Plan Validation — run `31322961365`;
- BUILD-617 Mechanistic Contradiction Validation — run `31322961299`;
- BRAIN-CANDIDATE-HANDOFF-004 — run `31322961315`;
- OC-PARALLEL-PLATFORM-001 — run `31322961316`;
- OC-PLATFORM-ROUTES-002 — run `31322961287`;
- CALYX Workflow Governance Audit — run `31322961297`;
- Calyx Brain Integration Validation — run `31322961280`;
- CALYX Brain End-to-End Certification — run `31322961290`.

## Findings corrected before readiness

The first executable pass exposed only formatting/integration findings: import organization in the shared Parallel Platform router and BUILD-620 test module, followed by formatter drift in the local-observation history projection. These were corrected without weakening scientific, behavioral, or governance gates.

## Governance

No scientific publication, species-level generalization, canonical Knowledge Graph mutation, production database mutation, deployment, taxonomy activation, or contradiction resolution is authorized. BUILD-620 remains a bounded local-evidence bridge only.
