# CRR-001A — Semantic Glossary Context for Speak with Calyx

## Status
Implementation slice for review.

## Purpose
Begin the Calyx Relationship Reasoning program by making the existing approved Orchid Continuum Lexicon available inside every non-casual Continuum context packet without waiting for figure completion.

## Audit findings

The current production architecture already contains the required seams:

- `app/calyx_conversation/speak_routes.py` builds a governed context packet for each turn.
- `app/calyx_conversation/continuum_context.py` already performs canonical read-only Knowledge Graph and Brain graph resolution.
- `app/lexicon/routes.py` exposes ACTIVE + APPROVED concepts and definitions from `oc_concepts`.
- `app/calyx_conversation/persona.py` already provides the conversational constitution and answer-first behavior.
- conversation responses already return the complete `research.continuum` object, so additive semantic metadata can reach clients without changing the public turn contract.

The missing seam was semantic resolution between the user's text and the approved Lexicon. Scientific terms such as `velamen` could exist in the Concept Registry but were not automatically surfaced to Calyx as clickable/explainable concepts during conversation.

## Implementation

### Semantic context resolver

`app/calyx_conversation/semantic_context.py`:

- creates bounded one-to-four-word candidate phrases from the user's turn;
- resolves exact normalized labels against `oc_concepts.concept_labels`;
- exposes only concepts whose concept and label review states are APPROVED and whose concept status is ACTIVE;
- selects an approved glossary/plain-language/scientific definition when available;
- returns a canonical `/api/lexicon/concepts/{concept_id}` href;
- degrades to an explicit unavailable state if the Concept Registry cannot be reached;
- performs no concept creation, promotion, mutation, or publication.

### Continuum handoff

`build_continuum_context()` now includes:

- `semantic_context`
- `semantic_links`

This means Speak with Calyx automatically supplies approved glossary concepts to both the generative provider and the API client because the existing conversation pipeline already forwards and returns Continuum context.

### Conversational policy

`CALYX-PERSONA-003` adds two requirements:

1. approved Lexicon terms are semantic doorways; Calyx may link the first natural occurrence using the supplied href while still defining specialized terminology in prose;
2. Calyx should connect morphology/anatomy -> function -> physiology -> environment -> interactions/evolution when supported, while preserving the distinction between documented relationships, correlations, inference, hypotheses, contradiction, and unknowns.

## Governance boundaries

This build does not:

- generate or approve glossary definitions;
- create etymologies or figures;
- promote candidate terminology;
- mutate the Knowledge Graph;
- infer causation from correlation;
- change scientific publication state;
- require the presence of artwork for glossary functionality.

## Acceptance behavior

A turn containing an approved concept such as `velamen` should return a semantic link object containing its canonical concept ID, approved definition when available, and Lexicon href. The same object is supplied to Calyx in governed context. A turn with no taxon name may still receive glossary context.

This is the first operational slice of CRR-001. Genus-wide evidence packets, Atlas action contracts, relationship-state materialization, comparative pattern analysis, and hypothesis refinement remain subsequent governed builds.
