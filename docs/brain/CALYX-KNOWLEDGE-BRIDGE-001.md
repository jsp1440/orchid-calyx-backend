# CALYX-KNOWLEDGE-BRIDGE-001 — Knowledge bridge production hardening

## Status

Implemented on the Calyx conversation knowledge bridge and preserved on the
`repair/remove-unauthorized-kalix` repair branch for integration into
`oc-autonomous-integration`.

## Architecture

Calyx is the Orchid Continuum reasoning agent. Its conversation knowledge
grounding reuses the existing Lexicon and Literature stores through stable,
read-only interfaces.

## Hardening changes

1. Literature enumeration uses
   `LiteratureResultRepository.list_paper_ids()` rather than scanning
   `repository.root` directly.
2. Lexicon retrieval uses the public
   `search_concepts(q=..., limit=...)` interface rather than importing the
   private `_load_entries` helper.
3. ACTIVE + APPROVED Lexicon filtering semantics are preserved.
4. Literature repository enumeration failures degrade safely to unavailable
   evidence rather than inventing data or aborting the conversation path.
5. Tests cover repository abstraction, the public Lexicon boundary, provenance,
   graceful failure, relevance filtering, and Calyx compatibility.

## Governance

- Read-only.
- No provider activation.
- No canonical Knowledge Graph mutation.
- No publication.
- No schema or production data mutation.
- Scientific filtering semantics are unchanged.

## Correction record

A separate named agent/persona called "Kalix" was introduced without owner
authorization. That architecture is rejected. The useful generic knowledge
bridge hardening is retained here under Calyx, the authorized reasoning agent.
