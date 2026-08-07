# CALYX Brain Record — Literature, Matrix, and AI.Vision

Date: 2026-08-07
Authoritative issue: #416
Authoritative PR: #417
Branch: `feature/literature-matrix-vision-engines`

## Purpose

Record the implemented state of the Literature Intelligence, Matrix Identification, and AI.Vision integration lane so future Calyx planning can distinguish executable capabilities from production dependencies.

## Delivered functional capabilities

### Literature Intelligence

- canonical source identity and SHA-256 content identity;
- evidence-span-bound claims;
- deterministic document-page ingestion contract;
- fail-closed OCR adapter boundary;
- accepted-name and synonym-aware taxonomy resolution contract;
- Candidate Knowledge payload planning;
- human-review approval required before any promotion plan;
- publication remains disabled.

### Matrix Identification

- versioned character definitions and taxon profiles;
- deterministic weighted candidate scoring;
- explicit support, contradiction, unknown, and missing-data accounting;
- per-character explainability;
- geography and flowering-month filters;
- accepted-name binding;
- confidence-margin abstention.

### AI.Vision

- licensed image identity and attribution requirements;
- model/provider/inference provenance;
- plant-part and visual-character observations;
- governed image-to-Matrix conversion;
- label/tag token extraction;
- provider-neutral inference boundary;
- unsupported near-certain confidence rejected;
- autonomous species publication disabled.

## Operator and governance layer

- protected Mission Control status and configuration routes;
- deterministic idempotent operation fingerprints;
- swappable operation repository contract;
- in-memory repository for non-production validation;
- human-review queue with pagination and filtering;
- approve/request-revision/reject transitions;
- audit export and per-operation provenance bundles;
- deterministic benchmark case registry;
- non-executing Candidate Knowledge promotion plans;
- inactive Postgres schema supplied for later governed migration.

## Safety state

The following remain disabled by design:

- live production AI.Vision inference;
- OCR provider activation;
- automatic Candidate Knowledge execution;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation;
- automatic merge and deployment.

## Validation strategy

The lane uses fixture-backed deterministic tests and CI covering compile, Ruff, scientific contracts, Matrix scoring, Vision licensing, abstention, operator review behavior, route mounting, provenance, and promotion gates. The full Mission Control router is mounted in `app.main` through the health router.

## Remaining production dependencies

1. Governed activation of Postgres persistence migration.
2. Real PDF/document adapter binding to Document Intelligence.
3. OCR provider selection and credentials through approved secret management.
4. Live AI.Vision provider selection and benchmark certification.
5. Curated, version-controlled orchid character matrices at useful taxonomic breadth.
6. Binding taxonomy resolution to the production Hassler/World Plants release service.
7. Real-world orchid image and literature benchmark sets.
8. Mission Control frontend panels for review, provenance, and candidate comparisons.
9. Explicit owner approval before Candidate Knowledge handoff execution.
10. Separate publication approval before any Knowledge Graph mutation.

## Governance conclusion

This build constitutes a governed functional engine and operator integration layer, not autonomous scientific publication. Human review remains the mandatory boundary between generated scientific evidence and promotion into authoritative knowledge.
