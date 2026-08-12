# CALYX-SCIENTIFIC-METHOD-GRAPH-001

## Purpose

The literature subsystem already extracts scientific structure richer than a publication citation. `PaperKnowledge` includes sections, taxon/entities, measurements, claims, evidence spans, normalized evidence records, relationships, figures, tables, references, review decisions and publication decisions. The Knowledge Graph must preserve this structure without promoting unreviewed extraction into canonical published knowledge.

## Implemented

`runtime/knowledge_graph/paper_knowledge_graph.py` is a pure converter from `PaperKnowledge` to canonical `NodeSpec`/`EdgeSpec` values. It performs no repository writes.

The converter now represents:

- publication metadata and analysis provenance;
- paper sections;
- evidence excerpts with source spans;
- reviewed observations, results, hypotheses, methodological claims, limitations, recommendations and assertions;
- reviewed measurements with value/unit/sample-size provenance;
- claim-to-evidence support edges;
- references and citations;
- figure evidence and table evidence;
- exact externally resolved taxon-to-publication `documented_by` edges.

Taxonomy is fail-closed. The converter never creates or fuzzy-matches a taxon from paper text. A caller must supply canonical graph keys from a separate taxonomy resolver.

## Knowledge-state governance

By default, scientific claims and measurements are emitted only when extraction provenance has review status `accepted` or `corrected`. Unreviewed candidate claims are omitted and counted in `candidate_objects_omitted`.

An explicit `include_candidates=True` mode exists only so candidate/review workflows can represent provisional extraction in a bounded context. It does not itself publish anything and must not be used to imply publication status.

Publication metadata, source sections, bibliographic references, figures/tables and evidence excerpts can be represented as source structure; extracted scientific interpretations remain review-gated.

## Validation

`tests/test_paper_knowledge_graph.py` verifies that:

- accepted/corrected scientific objects are represented;
- an unreviewed hypothesis is omitted by default;
- candidate representation requires explicit opt-in;
- claims retain support links to evidence excerpts;
- measurements retain evidence links;
- citations become reference nodes/edges;
- no taxon relationship is invented without resolver output.

The dedicated KG validation workflow now compiles and tests this mapping together with the bulk occurrence/trait source correction.

## Next integration

The remaining literature blocker is source-to-paper linkage: `public.research_documents` contains 6,725 documents, while the persisted graph contains only 29 publication nodes. The next source projection must determine where `PaperKnowledge` bundles/extraction outputs are persisted or how they map to `research_documents`, then resolve extracted taxon entities through the canonical taxonomy resolver before any governed graph publication.
