# BUILD-620-R2 Validation Record

Status: pending executable CI.

Integration base: BUILD-619-R2 / PR #788 (`feature/build-619-reasoning-scope-evaluation-r2`).

Scope: Matrix / Conservatory local-observation bridge only. Local observations enter Candidate Knowledge as review-required, unpublished, non-causal `CULTIVATION_OBSERVATION` evidence with bounded `n=1` applicability scope. Protected write/read routes expose submission and longitudinal history.

Validation gate: dedicated BUILD-620 workflow must pass compile, Ruff lint/format, BUILD-620 regressions, BUILD-619 and BUILD-618 prerequisite regressions, protected-route verification, and hygiene. Broad Brain/platform checks must not expose regressions.

Governance: no scientific publication, species-level generalization, canonical Knowledge Graph mutation, production database mutation, deployment, taxonomy activation, or contradiction resolution is authorized.
