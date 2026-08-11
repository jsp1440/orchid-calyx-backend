# CALYX-MULTIMODAL-WORKSPACE-001 — Adaptive multimodal Calyx workspace

## Status

Frontend workspace foundation and backend interaction-context bridge are implemented. Server-grounded workspace outputs and Lexicon ↔ Identification Matrix interoperability are implemented on release branches and await trusted validation before canonical merge.

Canonical frontend merges:

- `c50fa588499b9dc77fa02306b23fe51097078f35` — context-aware glossary workspace and session continuity.
- `7c5b1d8a88744f25003b4ea7995e86e3d94a9607` — shared multimodal workspace output bus and renderers.

Canonical backend merge:

- `2641bc6a874d7f3839de2235e5eaeb35d92596ef` — bounded server-side interaction context for Calyx (`CALYX-SPEAK-004-CONTEXT`).

Release branches awaiting validation:

- backend PR #873 / `feature/calyx-workspace-output-api-001` — server-grounded workspace outputs (`CALYX-SPEAK-005-WORKSPACE-OUTPUTS`).
- frontend PR #134 / `feature/calyx-server-workspace-output-bridge-001` — routes server outputs into the shared workspace bus.
- frontend branch `feature/calyx-lexicon-matrix-context-001` — bidirectional Lexicon ↔ Identification Matrix context/navigation.

## Architectural decision

Calyx is not a chat box competing with visual or scientific tools. The canonical interaction model is an adaptive workspace in which conversation remains present while multiple synchronized panels may display visual, analytical, spatial, literature, matrix, specimen, or other module outputs.

The migrated Famous AI Illustrated Orchid Lexicon is the first live surface using this architecture. The pattern is designed to generalize to Vision, Identification Matrix, Knowledge Graph, Literature, Conservatory, Research Station, Atlas, and future modules without each module creating a competing assistant or workspace implementation.

## Context awareness

Frontend session context records a bounded trail of the surfaces and objects currently viewed, including the active glossary concept. One server-owned Calyx conversation is retained across glossary terms for the browser session so natural follow-ups can resolve references such as "this structure" or "the term I was just looking at."

The canonical backend `CALYX-CONTEXT-001` bridge sanitizes this channel before it reaches a reply provider. Only bounded identifiers and display labels are accepted. Arbitrary nested metadata and arbitrary scientific claims are excluded. The server always asserts:

- `context_is_evidence = false`
- purpose = interaction continuity and reference resolution only
- maximum provider-visible session trail = 8 surfaces

Interaction context therefore cannot become scientific evidence, Candidate Knowledge, or a competing knowledge store.

## Multimodal workspace

The frontend workspace keeps conversation visible while resizable panes can simultaneously show:

- a concept visual;
- identification character context;
- related concepts;
- literature context;
- session trail;
- additional tool-produced outputs.

The shared output bus accepts validated output objects from any module. Current renderer kinds are:

- annotated image;
- diagram;
- chart;
- table / matrix-like output;
- text.

Every cross-module output requires provenance with a source module and an explicit evidence status: `evidence`, `derived`, `illustrative`, or `unknown`. Generated/derived output is visually labeled and is not promoted into canonical scientific knowledge.

## Server-grounded workspace outputs

`CALYX-SPEAK-005-WORKSPACE-OUTPUTS` derives auxiliary panels from actual Orchid Continuum module results rather than asking the language model to fabricate a tool result.

Initial producers are deliberately conservative:

- semantic retrieval results become a table of retrieved Orchid Continuum objects;
- governed Brain supporting/contradicting evidence becomes a comparison table;
- Brain mission missing-evidence items become an explicit uncertainty text panel;
- empty retrieval/mission state produces zero outputs.

Important epistemic distinction: retrieval alone does not establish scientific evidence status. The retrieval table therefore uses `evidence_status = unknown`, while preserving row-level review and verification states. Mission evidence and derived uncertainty remain separately labeled.

### Review hardening — 2026-08-11

Two P1 provenance defects found during review were repaired on backend PR #873 head `33aff16b37edc776525b89586df82778a7205c07`:

- retrieval rows now preserve each canonical retrieval `result_id` plus the citation payload, document ID, revision ID, and identifier; the ranking-configuration version is retained as ranking metadata rather than being misrepresented as the evidence source;
- Brain supporting/contradicting Candidate Knowledge panels are now explicitly `generated = true` and `evidence_status = derived`, with wording that prevents them from being mistaken for direct source evidence or conclusions.

Focused regression fixtures were strengthened to assert both boundaries. Both review threads are resolved. Executable CI certification remains pending because hosted runners are currently blocked before allocation by the account spending/billing gate described below.

The frontend bridge is fail-soft: malformed auxiliary outputs are withheld at the shared schema/provenance boundary and cannot discard an otherwise valid Calyx conversation turn.

## Lexicon ↔ Identification Matrix interoperability

`CALYX-LEXICON-MATRIX-001` establishes bidirectional navigation without asserting unsupported concept equivalence.

Lexicon → Matrix:

- a lexicon entry can open the Identification Matrix while carrying the active concept slug and label as UI/conversation context;
- that context is explicitly marked `context_is_observation = false`;
- the matrix does not silently insert the lexicon concept into the observation array.

Matrix → Lexicon:

- matrix character identifiers are humanized for display/search;
- character links open a lexicon search rather than inventing a canonical lexicon slug;
- the shared Calyx surface trail records the Matrix workspace and any originating lexicon concept, preserving conversational continuity across modules.

This is a navigation/context bridge, not a scientific mapping registry. Future canonical character↔concept mappings require reviewed semantic relationships and provenance.

## Scientific and governance boundaries

The workspace changes interaction, not publication authority.

- UI/session context is not evidence.
- Provider memory is not evidence.
- Retrieved objects are not automatically evidence merely because they were retrieved.
- Generated figures, charts, diagrams, and derived tables are not automatically evidence.
- Conversation does not publish knowledge.
- Candidate Knowledge is not auto-promoted.
- Knowledge Graph mutation is not authorized by the workspace.
- Scientific answers remain governed by Orchid Continuum evidence/review rules.

## Validation infrastructure blocker — 2026-08-11

GitHub Actions is currently refusing hosted-runner allocation for both the backend and frontend repositories before any workflow step executes. Check-run annotations state that recent account payments have failed or the Actions spending limit must be increased. Jobs show `runner_id = 0` and an empty step list.

This is an external billing/runner gate, not a demonstrated code failure. No billing setting or spending authorization should be changed automatically. Until trusted CI is available again, release branches must not be represented as CI-validated or merged solely by bypassing the gate.

Available engineering work may continue on branches, including patch review, pure-contract reasoning, tests committed for later execution, and documentation, while canonical merges that depend on Actions remain held.

## Next priorities

1. Restore a trusted validation path for backend #873 and frontend #134 without silently changing billing.
2. Execute the committed focused tests, build/lint, adjacent regressions, and review-thread checks; merge only after green validation.
3. Validate and merge `CALYX-LEXICON-MATRIX-001`.
4. Connect actual Matrix results as workspace-output producers.
5. Connect Vision image/annotation producers only when a real Vision tool has executed.
6. Configure and verify a genuine conversational model provider before calling production Calyx generative.
7. Complete the live Calyx Vision requirements conversation before releasing held Figure Labs generation.
