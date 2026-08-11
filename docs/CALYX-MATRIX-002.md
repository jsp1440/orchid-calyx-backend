# CALYX-MATRIX-002 — Guided Identification Session Vertical Slice

Parent architecture: `jsp1440/Orchid-Continuum-Brain#62`.

## Objective
Extend the existing deterministic Matrix Identification kernel and immutable registry into the first governed guided identification session.

## Preserve
- existing weighted matching semantics;
- certainty states;
- score vs coverage separation;
- per-character explanations;
- immutable registry versions/checksums;
- owner/API-key gating;
- no taxonomy mutation from identification.

## Implement in priority order
1. server-side candidate retrieval from immutable registry scope/canonical taxa;
2. persisted versioned identification sessions and append-only observation revisions;
3. deterministic next-best-observation recommendation from unresolved candidates;
4. reproducible saved identification report bound to registry checksum and revision history;
5. structured Calyx explanation context/response boundary;
6. review-gated image morphology suggestion contract aligned with current Calyx Vision governance.

## Guided-mode rule
The browser must not submit a full candidate matrix. It supplies registry/scope and observations; the server derives the candidate universe from governed data. Preserve raw/expert evaluator mode separately.

## Session evidence states
At minimum distinguish:
- direct_observation
- ai_suggestion
- inference
- reviewed

No AI suggestion may silently become reviewed evidence.

## Next-best-observation contract
Return a deterministic structured recommendation containing character ID, discriminatory/information-gain metric, missing-data penalty, candidate partition evidence or equivalent, reason code, human label, and optional acquisition mode such as observe/measure/front_image/lateral_image/vegetative_image.

Calyx may explain this recommendation but may not alter deterministic ranking or evidence-state fields.

## Vision boundary
Current Vision infrastructure is governed but live provider inference/durable activation remains separately controlled. Until activated, return explicit unavailable states or accept provenance-bearing review suggestions. Do not fake automatic morphology extraction.

## Acceptance tests
- identical registry + revision history => identical ranking and next-best recommendation;
- unknown observations contribute no score;
- missing candidate state lowers coverage and is not biological absence;
- candidate universe is server-derived in guided mode;
- stale revision cannot replace a newer revision;
- owner/tenant session isolation;
- explicit review transition required for AI suggestions;
- saved report preserves registry version/checksum and full revision history;
- Calyx prose cannot mutate score, coverage, candidate ordering or evidence state;
- no canonical taxonomy or Knowledge Graph mutation occurs.

## First pilot
Prefer a bounded `Angraecum` registry for continuity with the existing frontend demo only if governed/cited character assertions are available. Demonstration values are not scientific source data.

## Reporting
DONE
VALIDATION
MATRIX REALITY IMPACT
CALYX INPUT
VISION IMPACT
GOVERNANCE BOUNDARIES
NEXT SLICE
HANDOFF TO MASTER
