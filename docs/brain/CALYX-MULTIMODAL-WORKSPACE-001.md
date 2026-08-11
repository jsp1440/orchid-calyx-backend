# CALYX-MULTIMODAL-WORKSPACE-001 — Adaptive multimodal Calyx workspace

## Status

Implemented frontend foundation; backend interaction-context bridge in validation.

Canonical frontend merges:

- `c50fa588499b9dc77fa02306b23fe51097078f35` — context-aware glossary workspace and session continuity.
- `7c5b1d8a88744f25003b4ea7995e86e3d94a9607` — shared multimodal workspace output bus and renderers.

## Architectural decision

Calyx is not a chat box competing with visual or scientific tools. The canonical interaction model is an adaptive workspace in which conversation remains present while multiple synchronized panels may display visual, analytical, spatial, literature, matrix, specimen, or other module outputs.

The migrated Famous AI Illustrated Orchid Lexicon is the first live surface using this architecture. The pattern is designed to generalize to Vision, Identification Matrix, Knowledge Graph, Literature, Conservatory, Research Station, Atlas, and future modules without each module creating a competing assistant or workspace implementation.

## Context awareness

Frontend session context records a bounded trail of the surfaces and objects currently viewed, including the active glossary concept. One server-owned Calyx conversation is retained across glossary terms for the browser session so natural follow-ups can resolve references such as "this structure" or "the term I was just looking at."

The backend `CALYX-CONTEXT-001` bridge sanitizes this channel before it reaches a reply provider. Only bounded identifiers and display labels are accepted. Arbitrary nested metadata and arbitrary scientific claims are excluded. The server always asserts:

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

## Scientific and governance boundaries

The workspace changes interaction, not publication authority.

- UI/session context is not evidence.
- Provider memory is not evidence.
- Generated figures, charts, diagrams, and derived tables are not automatically evidence.
- Conversation does not publish knowledge.
- Candidate Knowledge is not auto-promoted.
- Knowledge Graph mutation is not authorized by the workspace.
- Scientific answers remain governed by Orchid Continuum evidence/review rules.

## Module interoperability

The output bus is intentionally module-neutral so the glossary and Identification Matrix can exchange context and visual outputs through one workspace contract. The same mechanism is intended for Vision regions/annotations, herbarium sheets, literature figures, maps, charts, and Knowledge Graph views.

The next backend slice should return server-derived `workspace_outputs` only from actual tool/module results. A language model must not invent a tool execution or fabricated visual object merely because it can describe one.

## Remaining dependencies

1. Validate and merge the backend context-awareness bridge.
2. Add a server-side workspace-output response contract derived from real module/tool outputs.
3. Connect actual Matrix/Vision/Literature producers incrementally.
4. Configure and verify a genuine conversational model provider before calling production Calyx generative.
5. Complete the live Calyx Vision requirements conversation before releasing held Figure Labs generation.
