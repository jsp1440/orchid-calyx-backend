# CALYX-LITERATURE-CORPUS-BRIDGE-001

## Problem

The live database contains 6,725 `public.research_documents` rows, while the persisted Knowledge Graph currently exposes only a small publication subset. Calyx therefore needs a governed retrieval bridge that can use the larger corpus before full publication-node materialization is complete.

## Implementation

`app/calyx_conversation/graph_literature_search.py` keeps the persisted graph as the primary literature path and adds a conservative exact-binomial fallback into `public.research_documents`.

The document fallback:

- activates only when the current message contains an explicit binomial taxon name;
- searches literal occurrences of that exact binomial in document title, abstract, or keywords;
- returns document id, title, DOI, year, type, and the exact taxon literal that matched;
- never creates a graph edge;
- labels provenance as `literal_binomial_mention` with `persisted_graph_edge=false` and `scientific_claim_inferred=false`;
- fills only remaining bounded result slots after persisted graph publication matches are collected.

This means Calyx can retrieve species-specific candidate papers from the large document corpus without pretending that a text mention is already a curated `documented_by` relationship or evidence for a scientific conclusion.

## Reviewed extraction evidence bridge

The repository already had canonical source bindings that cryptographically connect a `LITERATURE_DOCUMENT` source object to a `PaperKnowledge` extraction bundle and its exact evidence anchors. What was missing was the reverse read path from a research-document id back to those governed extraction results.

`FileLiteratureSourceBindingRepository.find_by_source_object()` now provides that bounded, read-only reverse lookup. `app/calyx_conversation/extracted_literature_evidence.py` then:

- resolves the research-document id to canonical extraction binding(s);
- reloads the persisted `PaperKnowledge` bundle and raw source bytes;
- revalidates the source hash and every exact evidence anchor before use;
- exposes only normalized evidence records whose recorded `PublicationDecision` is `eligible_for_publication`;
- preserves statement and normalized statement, scientific domain, polarity, canonical/unresolved entities, extraction and normalization confidence, review status, source excerpts, and exact evidence-anchor proofs;
- fails closed on malformed/tampered/incomplete extraction bundles;
- never changes review state, promotes Candidate Knowledge, publishes a record, or mutates the Knowledge Graph.

`graph_literature_search.py` attaches those publication-eligible evidence records to matching `public.research_documents` results when a canonical extraction binding exists. The deterministic and configured Calyx providers can therefore distinguish three different epistemic levels: persisted graph publication relationships, literal document discovery matches, and integrity-verified publication-eligible normalized evidence.

## Epistemic boundary

A research-document match by itself is discovery metadata, not a scientific finding. A publication-eligible normalized extraction record is stronger: its canonical binding and source anchors have been revalidated and it passed the recorded publication-eligibility gate. Calyx still must preserve the distinction between the source excerpt, normalized evidence record, and any higher-level synthesis or causal conclusion.

## Validation

Focused tests cover exact-binomial document matching, rejection of documents without the literal taxon, reverse source-binding lookup, integrity-verified publication-eligible evidence retrieval, provider distinction among graph/document/reviewed-evidence states, and explicit rendering of review/confidence metadata. The dedicated KG workflow compiles and tests these paths when GitHub allocates an executable runner.

GitHub-hosted Actions remains affected by the zero-step runner allocation incident; a job with `steps:null` is infrastructure non-execution and is not accepted as validation evidence.

## Status

Implementation-complete on PR #901 pending executable CI and live read-only acceptance. No production graph mutation is introduced by this bridge. The next scientific-literature integration step is materializing reviewed `PaperKnowledge` entities, observations, hypotheses, methods, measurements, results, conclusions, references, figures, and tables through the already-defined scientific-method graph vocabulary, after the corresponding publication-governance conditions are satisfied.
