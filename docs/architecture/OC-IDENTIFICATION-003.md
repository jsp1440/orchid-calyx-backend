# OC-IDENTIFICATION-003

## Mission

Build the canonical orchid candidate service on the merged structured-observation foundation.

## Implementation sequence

1. Add read-only canonical candidate repository protocols.
2. Apply taxonomic, geographic, seasonal, elevational, habitat, and size filters without converting missing data into negative evidence.
3. Score support, conflict, uncertainty, and missing observations separately.
4. Group look-alike taxa and identify the next observation with the highest discriminatory value.
5. Preserve candidate-suggestion, ambiguous, expert-review, and externally verified identity states.
6. Expose versioned candidate and session routes under `/api/platform/identification`.
7. Add deterministic fixtures, degraded data-source behavior, and focused/regression CI.

## Governance

Candidate suggestions are never verified identities. No taxonomy mutation, scientific publication, or automatic expert approval.

## Completion

Structured observations return explainable candidate sets with canonical identity references, provenance, conflicts, missing observations, look-alikes, and the next best question.
