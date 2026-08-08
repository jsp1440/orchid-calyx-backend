# CALYX-635 — Governed Knowledge Graph reads in Ask Calyx

Date: 2026-08-08
Depends on: CALYX-634 Ask the Continuum, canonical Knowledge Graph traversal, Evidence Retrieval 085B.
Status: implementation pending exact-head validation; no merge, deployment, scientific publication, external communication, or Knowledge Graph mutation authorized.

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

## Validation plan

Dedicated CALYX-635 CI will run:

- graph-tool and conversation integration tests;
- CALYX-634 conversation regressions;
- canonical Knowledge Graph traversal regressions;
- compilation;
- Ruff/diff hygiene;
- source-level non-authority assertions proving that the conversation graph adapter does not reference writable graph APIs or SQL mutation statements.

## Next priority after validation

Expose `graph_context` in Research Station Ask Calyx as a human-readable relationship panel so the researcher can inspect focal taxon, edge types, domain coverage, and data gaps without reading raw JSON.

No graph relationship becomes a new scientific conclusion merely because Calyx summarized its existence.
