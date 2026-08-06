# Priority Batch — BUILD-KE-305 through BUILD-BRAIN-116

Status: candidate implementation; draft only.

## Implemented vertical slices

1. **BUILD-KE-305** — integrated glossary cards with compact and expanded definitions, synonyms, related concepts, photographs/illustrations/diagrams/animations, alt text, licensing, evidence, and deterministic checksums.
2. **BUILD-ATLAS-406** — evidence-linked weighted conservation-priority candidates.
3. **BUILD-RS-503** — reproducible analysis manifests connecting code, environment, input checksums, and parameters while execution remains disabled.
4. **BUILD-CON-603** — deterministic staged QR label print jobs with duplicate-specimen rejection.
5. **BUILD-MATRIX-703** — interactive candidate elimination with explicit character-conflict explanations.
6. **BUILD-VISION-803** — confidence-ranked morphology extraction candidates tied to image evidence regions.
7. **BUILD-PUB-903** — reusable evidence-class-driven publication templates with publication disabled.
8. **BUILD-INT-954** — deterministic dead-letter records for unroutable or failed events, without automatic retry or external delivery.
9. **BUILD-MC-204** — approval dashboard projection separating ready items from items awaiting named review classes.
10. **BUILD-BRAIN-116** — deterministic semantic-discovery index manifests with provider activation disabled.

## Validation coverage

Focused tests cover glossary determinism, missing definitions, conservation weighting, duplicate analysis inputs, duplicate specimens, Matrix conflict explanations, duplicate visual observations, publication safeguards, timezone-aware dead-letter handling, missing approval classes, and discovery-index repeatability.

## Safety boundary

These are bounded candidate contracts. They do not approve glossary science, execute analyses, print labels, assert final identifications, publish morphology observations, publish documents, retry or deliver events externally, activate a vector/embedding provider, merge code, deploy services, or mutate the production Knowledge Graph.
