# CALYX-MATRIX-002 — Calyx Explanation Contract

This contract supports Brain issue `jsp1440/Orchid-Continuum-Brain#62`.

## Principle
Calyx explains governed Matrix evidence. Calyx does not own deterministic scoring, candidate ordering, evidence-state promotion, taxonomy mutation, or publication.

## Input context
A Matrix explanation request should contain a bounded structured context with:
- session_id and revision identity;
- registry_id/version/checksum;
- leading candidate results;
- score and coverage as distinct fields;
- per-character explanations/status;
- next-best-observation recommendation and its deterministic evidence;
- canonical taxon identifiers;
- optional lexicon concept identifiers;
- optional canonical literature/evidence references;
- optional image-suggestion objects with explicit review state.

Do not send unbounded repository/data dumps when a bounded context object can support the task.

## Supported explanation intents
- `why_top_candidate`
- `why_not_alternative`
- `why_next_observation`
- `character_help_beginner`
- `character_help_expert`
- `remaining_uncertainty`

## Output requirements
Every response must:
- identify explanation intent;
- preserve candidate IDs and evidence references;
- distinguish observation, suggestion, inference and reviewed/canonical evidence;
- avoid calling compatibility a probability unless calibrated;
- state important conflicts and unknowns rather than only supportive evidence;
- avoid changing ranking fields;
- retain mission/provider/review provenance through existing Calyx governance.

## Educational behavior
Beginner and expert explanations must map to the same canonical character identity. Beginner language may introduce terminology progressively; expert language may use formal botanical terminology and structured character states.

## Vision behavior
Calyx may explain an image-linked morphology suggestion only when a corresponding evidence/suggestion object exists. It must not invent masks, landmarks, measurements or organ detections.

## Failure behavior
If evidence is insufficient, return an explicit insufficient/unavailable state rather than generating a confident biological claim.
