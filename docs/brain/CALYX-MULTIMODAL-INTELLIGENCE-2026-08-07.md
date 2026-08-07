# CALYX Brain Record — Literature, Matrix, and AI.Vision

Date: 2026-08-07
Authoritative issue: #416
Authoritative PR: #571
Superseded PR: #417
Branch: `feature/literature-matrix-vision-current-main-release`

## Purpose

Record the implemented state of the Literature Intelligence, Matrix Identification, and AI.Vision integration lane so future Calyx planning can distinguish executable capabilities from production dependencies.

## Delivered functional capabilities

### Literature Intelligence

- canonical source identity and SHA-256 content identity;
- evidence-span-bound claims;
- deterministic document-page ingestion contract;
- read-only adapter from completed Document Intelligence records and extraction runs;
- fail-closed handling of incomplete runs, revision mismatch, and missing text;
- fail-closed OCR adapter boundary;
- accepted-name and synonym-aware taxonomy resolution contract;
- Candidate Knowledge payload planning;
- protected literature-validation execution endpoint;
- protected non-executing Candidate Knowledge promotion-plan endpoint;
- human-review approval required before a promotion plan can become eligible;
- publication remains disabled.

### Matrix Identification

- versioned character definitions and taxon profiles;
- deterministic weighted candidate scoring;
- explicit support, contradiction, unknown, and missing-data accounting;
- per-character explainability;
- geography and flowering-month filters;
- accepted-name binding;
- confidence-margin abstention;
- protected Matrix-ranking execution endpoint.

### AI.Vision

- licensed image identity and attribution requirements;
- model/provider/inference provenance;
- plant-part and visual-character observations;
- governed image-to-Matrix conversion;
- label/tag token extraction;
- provider-neutral inference boundary;
- protected Vision-conversion endpoint;
- protected integrated identification endpoint;
- unsupported near-certain confidence rejected;
- autonomous species publication disabled.

## Protected execution API

Deterministic execution routes require owner/API-key authentication and create governed operation records that enter human review:

- `POST /api/mission-control/multimodal-intelligence/literature/validate`
- `POST /api/mission-control/multimodal-intelligence/matrix/rank`
- `POST /api/mission-control/multimodal-intelligence/vision/convert`
- `POST /api/mission-control/multimodal-intelligence/identify`

These endpoints execute deterministic engine logic only. They do not activate live providers, publish scientific knowledge, mutate taxonomy, or write the production Knowledge Graph.

Human review is stricter than execution authentication: `POST /operations/{operation_id}/review` requires a signed owner session. Backend API-key authentication cannot approve review. The reviewer identity is derived from the signed owner-session actor and is not accepted from caller-controlled request data.

## Operator, persistence, and governance layer

- protected Mission Control status and configuration routes;
- typed Pydantic request contracts for literature, Matrix, Vision, and integrated identification;
- deterministic idempotent operation fingerprints;
- swappable operation repository contract;
- in-memory repository for deterministic validation;
- inert `PostgresOperationRepository` requiring an explicitly supplied connection factory;
- inactive Postgres schema supplied for later governed migration;
- human-review queue with pagination and filtering;
- approve/request-revision/reject transitions;
- signed owner-session-derived reviewer identity;
- audit export and per-operation provenance bundles;
- deterministic benchmark case registry;
- non-executing Candidate Knowledge promotion plans;
- no credentials read and no database connections opened at import or construction time.

## Safety state

The following remain disabled by design:

- live production AI.Vision inference;
- OCR provider activation;
- Postgres schema activation;
- automatic Candidate Knowledge execution;
- scientific publication;
- taxonomy activation;
- production Knowledge Graph mutation;
- automatic merge and deployment.

## Validation strategy and recovery evidence

The lane uses fixture-backed deterministic tests and CI covering compile, Ruff, scientific contracts, typed API contracts, Matrix scoring, Vision licensing, abstention, operator review behavior, route mounting, provenance, promotion gates, persistence construction, and the Document Intelligence bridge. The full Mission Control router is mounted in `app.main` through the health router.

The original #417 implementation passed executable run `31216240089` on implementation head `2f6d202501d8f1d2eb39d571291f3f642c92fbd3`: dependency installation, compile, Ruff, 41 focused tests, persistence-schema smoke, Brain-record smoke, real-app route smoke, and cleanup all succeeded.

## Current-main release recovery

PR #417 later became non-mergeable after substantial mainline advancement. PR #571 was rebuilt directly from authoritative main `3e617d644cefc9a106ebb9cb604b428d3bf63bb2` rather than forcing the stale branch.

The rebuild preserved the 23 additive multimodal source/workflow/test/migration/Brain blobs from the validated implementation byte-for-byte. The only shared application file, `app/routers/health.py`, was reconciled against current main so all newer Conservatory, Matrix Identification, Matrix Relationship, telemetry, archive, platform, and governance routes remain mounted while the multimodal router is added.

During current-main review, a governance defect was found and corrected before release: the old review request accepted a caller-supplied `reviewer` string despite authenticated access. PR #571 removes that trusted field, requires `auth_type=owner_session` for review decisions, derives the reviewer from the signed authentication principal, rejects API-key review with `HUMAN_REVIEW_OWNER_SESSION_REQUIRED`, and rejects missing owner identity with `HUMAN_REVIEW_IDENTITY_REQUIRED`. Focused tests cover both allowed and fail-closed paths.

Exact implementation head `a4785a0f68a65f61c7d0a2540e0cf3ee578c0662` passed all 12 triggered workflows:

- Literature Matrix Vision Engines Validation `31223893116` — success;
- CALYX Workflow Governance Audit `31223893175` — success;
- BUILD-088E Validation `31223893201` — success;
- CALYX-AUTONOMY-DEPLOYMENT-001 `31223893128` — success;
- WORLD-PLANTS-UPLOAD-001 `31223893167` — success;
- CONSERVATORY-MVP-001 `31223893182` — success;
- MATRIX-IDENTIFICATION-MVP-001 `31223893178` — success;
- MATRIX-RELATIONSHIP-MVP-001 `31223893155` — success;
- OC-PARALLEL-PLATFORM-001 Validation `31223893230` — success;
- BUILD-080 Archive Validation `31223893212` — success;
- BUILD-074 validation `31223893226` — success;
- BUILD-070 Validation `31223893197` — success.

The dedicated multimodal workflow passed dependency installation, compile, Ruff, the expanded focused test set, persistence-schema smoke, Brain-record smoke, real-app route smoke, and cleanup. The cross-platform matrix establishes that the current-main health-router reconciliation does not regress the newer routed systems.

## Remaining production dependencies

1. Governed activation of the Postgres persistence migration and repository selection.
2. OCR provider selection and credentials through approved secret management.
3. Binding taxonomy resolution to the production Hassler/World Plants release service.
4. Live AI.Vision provider selection and benchmark certification.
5. Curated, version-controlled orchid character matrices at useful taxonomic breadth.
6. Real-world orchid image and literature benchmark sets.
7. Mission Control frontend panels for execution, review, provenance, and candidate comparisons.
8. Explicit owner approval before Candidate Knowledge handoff execution.
9. Separate publication approval before any Knowledge Graph mutation.

## Governance conclusion

This build constitutes a governed functional engine and operator integration layer, not autonomous scientific publication. Human review remains the mandatory boundary between generated scientific evidence and promotion into authoritative knowledge.
