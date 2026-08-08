# BUILD-613 — Calyx Causal Reasoning Context

## Status

Implemented on `feature/build-613-calyx-reasoning-context`, pending validation and merge.

## Purpose

BUILD-613 makes the BUILD-612 causal reasoning map operational from Calyx without asking a language model to invent an opaque chain of reasoning. It reuses the deterministic, evidence-bearing `ReasoningMapEngine` as a read-only scientific context layer and combines it with the existing Orchid Continuum evidence retrieval engine.

This is the first Calyx-facing bridge between causal Knowledge Graph pathways and conversational scientific analysis.

## Integration boundary

BUILD-613 intentionally does not rewrite the existing Phase 2 `/api/calyx/query` contract in the first integration slice. Instead it introduces two dedicated endpoints so the reasoning behavior can be validated independently before it becomes an optional context inside the general conversation pipeline.

### `POST /api/calyx/reasoning-map`

Returns the inspectable BUILD-612 causal map for a focal Knowledge Graph node.

Supported controls include:

- forward, backward, or bidirectional traversal;
- biological mechanism, phenotype expression, cultivation diagnosis, evidence trace, or unrestricted profiles;
- bounded depth and result count;
- optional edge-type filters;
- causal-only traversal.

### `POST /api/calyx/reasoning-query`

Combines:

1. a deterministic read-only causal reasoning map;
2. indexed Orchid Continuum evidence retrieval;
3. an explicit human-readable summary of the highest-priority inspectable pathways;
4. confidence and polarity information;
5. an epistemic boundary stating that a graph pathway is an explanatory hypothesis structure, not proof of causality.

The response includes the complete reasoning map and retrieval results rather than returning only prose.

## Scientific behavior

A pathway can represent a biological chain such as:

`environment -> physiology -> cellular/developmental process -> phenotype`

or, as the graph becomes richer:

`gene -> protein -> regulation/signaling -> tissue/anatomy -> physiology -> development -> phenotype -> ecological/cultivation outcome`

BUILD-613 does not create those scientific relationships. It exposes and explains relationships already represented in canonical Knowledge Graph state and preserves the BUILD-612 evidence/provenance envelope.

## Governance

The Calyx reasoning endpoints are fail-closed and read-only.

They do not:

- mutate canonical Knowledge Graph state;
- automatically publish scientific claims;
- convert an inferred pathway into accepted knowledge;
- bypass the Reasoning Ledger or publication controls;
- treat graph connectivity as proof of causality.

The `/reasoning-query` response explicitly reports:

- Continuum-first evidence policy;
- reasoning-map read-only status;
- no generative scientific claims without evidence;
- no automatic scientific publication;
- no Knowledge Graph mutation.

## Validation

`tests/test_build_613_calyx_reasoning_context.py` covers:

- reuse of the BUILD-612 Brain engine from Calyx;
- multi-step causal pathway output and polarity;
- preservation of no-mutation governance;
- inspectable pathway rendering;
- explicit causality/proof boundary;
- authenticated `/calyx/reasoning-map` behavior;
- combination of reasoning pathways and indexed evidence in `/calyx/reasoning-query`;
- fail-closed unknown-node behavior.

The Calyx Conversation validation workflow has been expanded so BUILD-613 code and tests are compiled, executed, linted, and route registration is verified for both new endpoints.

## Relationship to the Matrix

BUILD-613 establishes the query interface the Matrix can later call after translating measured plant, environment, growth, or cultivation observations into governed analytical context. The canonical Knowledge Graph remains scientific memory; the reasoning map supplies causal structure; the Matrix supplies quantitative observations and models; Calyx provides the conversational and explanatory surface.

## Next highest-value extension after validation

Once this dedicated adapter is certified, the next integration should add an optional `reasoning_map` request to the existing `/api/calyx/query` conversation contract and persist a compact reasoning-map summary with the conversation/report. That change should preserve backward compatibility and keep the full reasoning artifact inspectable outside generated prose.
