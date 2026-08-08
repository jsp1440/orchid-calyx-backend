# CALYX-635 — Governed Knowledge Graph reads in Ask Calyx

Date: 2026-08-08
Depends on: CALYX-634 Ask the Continuum, canonical Knowledge Graph traversal, Evidence Retrieval 085B.
Status: backend and Research Station integration validated on exact heads and promoted to review. No merge, deployment, scientific publication, external communication, or Knowledge Graph mutation authorized.

## Goal

Extend Ask Calyx from literature/evidence retrieval into the existing canonical Knowledge Graph without granting conversation any write authority.

CALYX-635 adds this bounded path:

`operator question + active taxon context -> Evidence Retrieval -> read-only Knowledge Graph lookup -> provenance-preserving conversational envelope`

The Knowledge Graph is invoked only when `active_taxon_id` is supplied in conversation context. Project and document context remain context only and do not silently trigger graph lookup.

## Graph tool boundary

`runtime/continuum_graph_tool.py` depends only on the existing `GraphRepository` read contract and defaults to `PostgresGraphRepository` when `DATABASE_URL` is configured. It does not import or instantiate `WritablePostgresGraphRepository`.

Permitted graph operations:

- resolve a taxon canonical key;
- read the focal node;
- traverse outgoing graph edges through the existing traversal service;
- return nodes, edges, relationship types, domain coverage, explicit data gaps, pagination, and provenance already present in the graph objects.

Permanent assertions:

- `read_only=true`;
- `knowledge_graph_mutation_authorized=false`;
- `model_knowledge_used=false`;
- `scientific_interpretation_generated=false`;
- `scientific_publication_authorized=false`.

If the database is not configured, the tool returns `status=unavailable`. If a supplied taxon cannot be resolved, it returns `status=not_found`. Neither condition is replaced with guessed relationships.

## Conversation behavior

The conversation response schema advances to `calyx-continuum-conversation/v2` and adds:

- `graph_context`;
- `knowledge_graph_read_authorized=true`;
- a `knowledge_graph_read` tool-trace record when a taxon lookup is attempted.

New epistemic states are additive:

- `continuum_graph` — graph context exists but retrievable evidence text does not;
- `continuum_evidence_and_graph` — both authorized evidence excerpts and graph traversal are available;
- `continuum_graph_and_evidence_metadata` — graph traversal plus metadata-only evidence.

Existing `unknown`, `continuum_evidence`, and `continuum_evidence_metadata_only` states remain valid when graph traversal is not available or was not requested by context.

Graph answer text is deliberately descriptive. It may state the number of connected nodes/edges, recorded edge types, represented domains, and explicit data gaps. It must state that these are stored graph relationships and coverage signals, not a newly inferred causal or scientific interpretation.

## Backend validation evidence

Behavioral head `b02ce7c8099757f8fad211260dd9388e22ed60d5` passed:

- CALYX-634 conversation compatibility lane;
- global CALYX workflow-governance audit;
- CALYX-635 graph conversation lane;
- 29 stacked graph/conversation/traversal tests;
- permanent read-only Knowledge Graph assertions;
- changed-surface Ruff and diff hygiene.

The subsequent Brain documentation head `edafb0445f9d8e95bb096a6694c08a9763053068` also passed all three exact-head lanes: CALYX-634 compatibility, CALYX-635 graph conversation, and workflow-governance audit. Backend PR `#642` was therefore promoted from draft to review and remains unmerged/non-production.

The first CALYX-635 run exposed only code-quality issues after all behavioral tests passed: Ruff requested import normalization and rejected a broad `Exception` catch. Those were corrected by formatting imports and narrowing database read failure handling to `psycopg.Error`. No behavioral authority was broadened by the fixes.

The prior CALYX-634 lane also remained behavior-clean during development: its 18 conversation/retrieval tests and non-authority assertions passed before the import-format correction.

## RS-8 human interface integration

Research Station PR `#8`, branch `feature/research-calyx-graph-8`, exposes the CALYX-635 graph packet in the existing project-scoped Ask Calyx workspace.

RS-8 adds:

- typed graph context layered over the RS-7 conversation response;
- project-linked taxon discovery through the existing authenticated Research Station client;
- an explicit `Evidence only` / linked-taxon selector;
- automatic preselection only when exactly one linked taxon exists;
- no silent taxon selection when multiple linked taxa exist;
- selected taxon routing through `active_taxon_id` on the existing Ask Calyx request;
- a human-readable graph panel showing focal taxon, node/edge counts, relationship types, domain coverage, connected objects, evidence class, confidence labels, provenance, and explicit data gaps;
- explicit not-found/unavailable graph rendering;
- continued display of the no-model-memory, no-publication, and no-Knowledge-Graph-mutation boundary.

RS-8 exact head `6274ac5a7eb3be8e013d2a32afb8e55afd9d87bf` passed the complete Research Station CI sequence: formatting normalization and verification, both lint stages, full tests, and production build. Frontend PR `#8` was promoted from draft to review and remains unmerged/non-production.

## Next priority

The next high-value conversational layer is persistent conversation/session context plus explicit tool-selection history, so Calyx can sustain a research thread across multiple questions without treating prior conversation as canonical scientific evidence. That work should preserve the same evidence/graph provenance envelopes and governance boundaries.

No graph relationship becomes a new scientific conclusion merely because Calyx summarized or displayed its existence.
