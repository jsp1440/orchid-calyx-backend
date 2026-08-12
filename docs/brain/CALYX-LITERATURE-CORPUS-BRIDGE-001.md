# CALYX-LITERATURE-CORPUS-BRIDGE-001

## Problem

The live database contains 6,725 `public.research_documents` rows, while the persisted Knowledge Graph currently exposes only a small publication subset. Calyx therefore needs a governed retrieval bridge that can use the larger corpus before full publication-node materialization is complete.

## Implementation

`app/calyx_conversation/graph_literature_search.py` now keeps the persisted graph as the primary literature path and adds a conservative exact-binomial fallback into `public.research_documents`.

The fallback:

- activates only when the current message contains an explicit binomial taxon name;
- searches literal occurrences of that exact binomial in document title, abstract, or keywords;
- returns document id, title, DOI, year, type, and the exact taxon literal that matched;
- never creates a graph edge;
- labels provenance as `literal_binomial_mention` with `persisted_graph_edge=false` and `scientific_claim_inferred=false`;
- is used only to fill remaining bounded result slots after persisted graph publication matches are collected.

This means Calyx can retrieve species-specific candidate papers from the large document corpus without pretending that a text mention is already a curated `documented_by` relationship or evidence for a scientific conclusion.

## Epistemic boundary

A research-document match is discovery metadata, not a scientific finding. The paper text or governed extraction must still be inspected before claims, methods, observations, results, measurements, or conclusions are treated as evidence.

## Validation

Focused tests verify that literal `Laelia anceps` matches are returned with nonclaim provenance and that documents lacking the literal binomial are rejected. The dedicated KG workflow now compiles and tests this bridge when GitHub allocates an executable runner.

## Status

Implementation-complete on PR #901 pending executable CI and live read-only acceptance. No production graph mutation is introduced by this bridge.
