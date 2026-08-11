# CALYX-MULTIMODAL-WORKSPACE-001 — Adaptive multimodal Calyx workspace

## Status

Frontend workspace foundation and backend interaction-context bridge are canonical. Server-grounded outputs and Matrix interoperability are implemented on ordered release branches and await trusted validation before canonical merge.

Canonical frontend merges:

- `c50fa588499b9dc77fa02306b23fe51097078f35` — context-aware glossary workspace and session continuity.
- `7c5b1d8a88744f25003b4ea7995e86e3d94a9607` — shared multimodal workspace output bus and renderers.

Canonical backend merge:

- `2641bc6a874d7f3839de2235e5eaeb35d92596ef` — bounded server-side interaction context for Calyx (`CALYX-SPEAK-004-CONTEXT`).

Release chain awaiting trusted validation:

- backend PR #873 / `feature/calyx-workspace-output-api-001` — server-grounded Speak workspace outputs (`CALYX-SPEAK-005-WORKSPACE-OUTPUTS`).
- backend PR #874 / `feature/calyx-matrix-workspace-output-001` — Matrix Identification derived ranking panel; intentionally targets #873's branch.
- frontend PR #134 / `feature/calyx-server-workspace-output-bridge-001` — routes server Speak outputs into the shared workspace bus.
- frontend PR #135 / `feature/calyx-lexicon-matrix-context-001` — bidirectional Lexicon ↔ Identification Matrix context/navigation.
- frontend PR #136 / `feature/calyx-matrix-adaptive-workspace-001` — shared Calyx session, Matrix conversation surface, reusable output dock, and Matrix result ingestion; intentionally targets #135's branch.

## Architectural decision

Calyx is not a chat box competing with visual or scientific tools. The canonical interaction model is an adaptive workspace in which conversation remains present while multiple synchronized panels may display visual, analytical, spatial, literature, matrix, specimen, or other module outputs.

The migrated Famous AI Illustrated Orchid Lexicon is the first live surface using this architecture. The pattern generalizes to Vision, Identification Matrix, Knowledge Graph, Literature, Conservatory, Research Station, Atlas, and future modules without each module creating a competing assistant or workspace implementation.

## Context awareness

Frontend session context records a bounded trail of surfaces and objects currently viewed. A server-owned Calyx conversation is retained across adaptive-workspace surfaces so natural follow-ups can resolve references such as "this structure", "that character", or "the term I was just looking at."

The canonical backend `CALYX-CONTEXT-001` bridge sanitizes this channel before it reaches a reply provider. Only bounded identifiers and display labels are accepted. Arbitrary nested metadata and arbitrary scientific claims are excluded. The server always asserts:

- `context_is_evidence = false`
- purpose = interaction continuity and reference resolution only
- maximum provider-visible session trail = 8 surfaces

Interaction context therefore cannot become scientific evidence, Candidate Knowledge, or a competing knowledge store.

## Multimodal workspace

The frontend keeps conversation visible while panes can simultaneously show concept visuals, identification character context, related concepts, literature, session context, and additional tool-produced outputs.

The shared output bus accepts validated module-neutral objects. Renderer kinds are:

- annotated image;
- diagram;
- chart;
- table / matrix-like output;
- text.

Every output requires provenance with a source module and explicit evidence status: `evidence`, `derived`, `illustrative`, or `unknown`. The shared bus rejects unsupported evidence labels, malformed image annotations, malformed table/chart shapes, and empty text outputs. Batch ingestion is fail-soft: one malformed auxiliary panel does not discard the primary scientific result or Calyx conversation.

## Server-grounded Speak outputs

`CALYX-SPEAK-005-WORKSPACE-OUTPUTS` derives auxiliary panels from actual Orchid Continuum module results rather than asking the language model to fabricate a tool result.

Initial producers are deliberately conservative:

- semantic retrieval results become a table of retrieved Orchid Continuum objects;
- governed Brain supporting/contradicting evidence becomes a comparison table;
- Brain mission missing-evidence items become an explicit uncertainty text panel;
- empty retrieval/mission state produces zero outputs.

Retrieval alone does not establish scientific evidence status. The retrieval table therefore uses `evidence_status = unknown`, while preserving row-level review and verification states. Mission evidence and derived uncertainty remain separately labeled.

## Lexicon ↔ Identification Matrix interoperability

`CALYX-LEXICON-MATRIX-001` establishes bidirectional navigation without asserting unsupported concept equivalence.

Lexicon → Matrix:

- a lexicon entry can open the Identification Matrix carrying the active concept slug and label as UI/conversation context;
- that context is explicitly `context_is_observation = false`;
- the Matrix does not silently insert the lexicon concept into the observation array.

Matrix → Lexicon:

- matrix character identifiers are humanized for display/search;
- character links open a lexicon search rather than inventing a canonical lexicon slug;
- the shared Calyx surface trail records the Matrix workspace and originating lexicon concept.

This is a navigation/context bridge, not a scientific mapping registry. Future canonical character↔concept mappings require reviewed semantic relationships and provenance.

## Matrix as a real workspace-output producer

`CALYX-MATRIX-WORKSPACE-001` derives an auxiliary table from the actual result returned by `runtime.matrix_identification.rank_candidates`.

The output is bounded to 20 candidates and carries:

- rank;
- scientific name;
- canonical/source taxon identifier supplied to the matrix;
- match percentage;
- coverage percentage;
- compared weight.

Its provenance is:

- `source_module = matrix-identification`
- `generated = true`
- `evidence_status = derived`

The panel explicitly states that the ranking supports review and does not assert a verified identification. The underlying detailed explanation response remains the primary Matrix result and is not replaced by the panel.

The frontend Matrix workspace keeps Calyx conversation, the derived output dock, and the detailed explainable ranking available simultaneously. The adaptive browser-session conversation now spans Lexicon and Matrix surfaces rather than creating module-specific assistant silos.

## Vision integration gate

Canonical Vision activation documentation currently reports that live provider inference remains false. Therefore the adaptive workspace must not fabricate Vision annotations, segmentation, bounding boxes, or generated diagrams. Vision image/annotation workspace outputs become eligible only after a real governed Vision provider has executed and returned an artifact with provenance.

This restriction is independent of Figure Labs. Held Figure Labs bulk generation remains behind the live Calyx Vision self-requirements review and should not be consumed merely to populate UI panels.

## Conversational provider prerequisite

`app/calyx_conversation/provider.py` supports an OpenAI-compatible configured provider only when both `CALYX_CHAT_COMPLETIONS_URL` and `CALYX_CHAT_MODEL` are configured. Otherwise Speak uses the explicitly identified deterministic governed fallback.

The deterministic fallback is useful for honest evidence formatting but is not equivalent to a genuinely generative scientific collaborator. Provider readiness must therefore be exposed and tested explicitly before production Speak is described as fully generative or before the live Calyx Vision requirements conversation is treated as completed.

## Scientific and governance boundaries

The workspace changes interaction, not publication authority.

- UI/session context is not evidence.
- Provider memory is not evidence.
- Retrieved objects are not automatically evidence merely because they were retrieved.
- Matrix rankings are derived analytical outputs, not verified identifications.
- Generated figures, charts, diagrams, and derived tables are not automatically evidence.
- Conversation does not publish knowledge.
- Candidate Knowledge is not auto-promoted.
- Knowledge Graph mutation is not authorized by the workspace.
- Scientific answers remain governed by Orchid Continuum evidence/review rules.

## Validation infrastructure blocker — 2026-08-11

GitHub Actions is refusing hosted-runner allocation for both backend and frontend before any workflow step executes. Check-run annotations state that recent account payments have failed or the Actions spending limit must be increased. Jobs show `runner_id = 0` and an empty step list.

This is an external billing/runner gate, not a demonstrated code failure. No billing setting or spending authorization should be changed automatically. Until trusted CI is available again, release branches must not be represented as CI-validated or merged by bypassing the gate.

Available engineering work may continue on branches, including patch review, pure-contract reasoning, tests committed for later execution, and documentation, while canonical merges that depend on Actions remain held.

## Next priorities

1. Expose a secret-safe Calyx conversational-provider readiness contract and add acceptance tests that distinguish deterministic fallback from configured generative mode.
2. Restore a trusted validation path for backend #873/#874 and frontend #134/#135/#136 without silently changing billing.
3. Execute the committed focused tests, build/lint, adjacent regressions, and review-thread checks; merge in dependency order only after green validation.
4. Run a genuine live Speak acceptance conversation through a configured provider and governed evidence path.
5. Run the Calyx Vision self-requirements review through that tested Speak surface.
6. Activate a real Vision provider before adding Vision image/annotation output producers.
7. Release Figure Labs generation only after the Vision requirements gate is satisfied.
