# CALYX AI.Vision governed image analysis and Matrix handoff — issue #450

Date: 2026-08-07
Depends on: Matrix operational contracts #449 and immutable artifact/evidence registry
Status: implementation complete pending exact-head CI validation; no deployment, taxonomy activation, publication, or production graph mutation performed.

## Goal

Provide a governed AI.Vision vertical slice that can accept externally produced orchid image-analysis results, preserve media/model/prompt provenance, reject unsupported or unlicensed inputs, create uncertain character observations, and hand those observations into the existing Matrix Identification workflow without making an autonomous taxonomic determination.

Lifecycle:

`licensed image identity → model/prompt provenance → plant-part detections → uncertain character observations → human correction/review → governed Matrix observation conversion → saved Matrix session`

## Reused canonical boundaries

This build intentionally reuses existing Orchid Continuum infrastructure instead of creating parallel authority:

- `app.multimodal_intelligence.contracts.ImageAnalysisResult` for image-analysis validation;
- `ModelProvenance`, `PlantPartDetection`, and `CharacterObservation` contracts;
- `matrix_observations_from_vision()` for vision-to-Matrix conversion;
- `runtime.matrix_operational.create_identification_session()` for ranked identification sessions;
- `ImmutableArtifactRegistry` for evidence-bearing analysis artifacts.

The Matrix handoff remains candidate ranking evidence only. It does not activate taxonomy or assert a definitive species identification.

## Image identity, rights, and provenance

Each submitted analysis preserves:

- caller-supplied immutable image ID;
- SHA-256 image checksum;
- canonical HTTP(S) source URL;
- normalized allowlisted license;
- creator and attribution;
- acquisition timestamp;
- taxon-resolution state and optional canonical taxon ID;
- model provider, name, version, and inference ID;
- prompt ID, version, and SHA-256.

Allowlisted media licenses are deliberately conservative: CC0, CC BY, CC BY-SA, and public-domain forms represented in the service allowlist. Missing attribution or an unapproved license fails closed.

## Analysis contracts

Plant-part detections carry explicit confidence. Character observations carry character ID, state, confidence, and provenance.

Existing multimodal validation rejects malformed confidence and unsupported AI.Vision confidence values above the governed ceiling. The build therefore cannot silently promote machine output into certainty.

Submitted records also permanently report:

- `live_provider_call=false`;
- `face_or_person_analysis=false`;
- `autonomous_species_identification=false`;
- `taxonomy_activation_authorized=false`;
- `scientific_publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

## Human correction and review

A reviewer may add a correction to one uniquely identified character observation. Correction records preserve:

- character ID;
- original state;
- corrected state;
- reviewer identity;
- rationale;
- review timestamp.

Corrections do not alter the immutable raw AI observation. They are appended as a review layer and the analysis returns to `corrected_review_required` state.

## Matrix handoff

AI.Vision observations are converted into the existing Matrix session input contract using confidence-derived certainty plus confidence weighting. Human-corrected states override machine states only at the governed handoff layer.

The resulting Matrix session preserves the existing #449 behavior:

- deterministic replay identity;
- ranked candidate evidence;
- support/contradiction/unknown/missing-data accounting;
- per-character explanation;
- confidence bounds;
- human review required;
- no definitive identification authority.

## Protected Mission Control API

Owner/API-key protected routes are exposed under:

`/brain/mission-control/vision`

- `POST /analyses` — register one governed externally produced image-analysis result;
- `GET /analyses/{analysis_id}` — retrieve preserved analysis status and provenance;
- `POST /analyses/{analysis_id}/corrections` — append a human correction/review record;
- `POST /analyses/{analysis_id}/matrix-handoff` — convert reviewed/uncertain observations into the existing Matrix session workflow.

## Artifact registration

Each new analysis is registered in the immutable artifact registry with:

- deterministic artifact ID;
- exact serialized analysis content;
- media source URI;
- license;
- evidence URI;
- image checksum and model metadata.

The registry's evidence requirement is checked before the analysis workspace record is finalized.

## Deterministic orchid fixture

Focused tests use an orchid flower/tag image pair represented by deterministic metadata/checksums rather than live provider calls. The fixture verifies:

- accepted licensed flower/tag analyses;
- image/model/prompt provenance retention;
- confidence/plant-part/character contracts;
- unlicensed-media rejection;
- unsupported-confidence rejection;
- human correction records;
- Matrix observation conversion and close-candidate ranking;
- protected status API;
- replay behavior.

No external computer-vision service is called by the fixture.

## Validation

Dedicated workflow:

`.github/workflows/calyx-ai-vision-450.yml`

Validation covers:

- Python compilation;
- focused AI.Vision fixture tests;
- Matrix operational regressions;
- multimodal engine regressions;
- artifact-registry regressions;
- permanent governance assertions;
- Ruff and `git diff --check`.

## Explicit non-actions

No live autonomous image inference, face/person analysis, autonomous species determination, unlicensed promotion, taxonomy activation, scientific publication, production Knowledge Graph mutation, deployment, merge, or fabricated production counts are authorized by this build.
