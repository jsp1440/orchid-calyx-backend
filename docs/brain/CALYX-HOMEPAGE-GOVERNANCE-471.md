# CALYX-471 — Homepage audit, redesign specification, and release governance

Status: IMPLEMENTED / VALIDATION PENDING / GOVERNED RELEASE-ONLY

## Delivered

- Versioned `HomepageAuditV1` records preserving deployed revision, source screenshot artifact identity/checksum/source URI/capture time, route inventory, findings, evidence anchors, and provenance.
- Versioned `HomepageRedesignSpecificationV1` records linked cryptographically to the audited revision and carrying required sections/routes/components plus visual, accessibility, scientific wording, taxonomy, media, and evidence requirements.
- Explicit owner approval transition before implementation intake is accepted.
- Implementation-manifest intake preserving implementation revision, screenshot evidence, returned artifact metadata, and provider identity without treating Famous AI or another implementation provider as scientific authority.
- Deterministic specification-vs-implementation comparison for required sections, routes, and components.
- Required visual, accessibility, scientific, taxonomy, media, and evidence validation gates. A passing gate must include evidence; unsupported PASS claims fail closed.
- Canonical taxon references are checked against the CALYX-467 species dossier workspace. Unresolved stable taxon IDs block release eligibility.
- Release readiness is available only after all validation checks pass, the manifest matches the approved specification, canonical taxon references resolve, and no blockers remain.
- Protected Mission Control audit/specification/approval/implementation/validation/readiness APIs and focused deterministic tests.

## Integration model

CALYX-471 is stacked on the validated CALYX-467 species dossier branch so homepage taxonomy references use the same stable taxon identity contract rather than creating a parallel identity system. Media and evidence validation remain explicit governed validation receipts; the pipeline does not fabricate provider readiness when upstream media/evidence systems are unavailable.

The pipeline can preserve a Famous AI implementation brief and returned artifact metadata, but `implementation_provider_scientific_authority=false` is permanent. Implementation tooling executes an approved design specification; it does not decide taxonomy, evidence quality, or scientific wording validity.

## Governance boundaries

No automatic deployment, no unreviewed homepage activation, and no scientific publication authority exists. `release_eligible` is a review state only: it still reports `owner_activation_required=true`, `automatic_deployment_authorized=false`, and `unreviewed_activation_authorized=false`.

Tests and validation use fixtures only and do not activate a live homepage, deploy frontend code, mutate production data, or publish science.

## Validation

Dedicated CI compiles the homepage governance surface, runs CALYX-471 tests plus CALYX-467 species-dossier regressions, asserts permanent no-auto-deployment/no-unreviewed-activation boundaries, runs Ruff, and checks diff hygiene. Record exact-head validation evidence here after the pull-request workflow completes.
