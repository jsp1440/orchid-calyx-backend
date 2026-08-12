# CALYX-SCIENTIFIC-METHOD-GRAPH-BRIDGE-001

## Purpose

Close the next integration gap after connecting Calyx to the bulk occurrence corpus and the 6,725-document research corpus: reviewed literature extraction must become graph-shaped scientific evidence rather than remaining a disconnected JSON artifact.

## Problem identified

`PaperKnowledge` already models paper structure, entities, measurements, observations, hypotheses, methods, results, interpretations, limitations, recommendations, evidence spans, references, figures and tables. The existing graph mapper could represent many of those objects, but its default claim gate relied only on extraction provenance review status. That is weaker than the literature pipeline's explicit `PublicationDecision` contract. It also did not connect eligible claim/measurement nodes directly back to canonical taxon nodes.

## Implemented

### Strict publication-eligible graph projection

Added `runtime/knowledge_graph/publication_eligible_paper_graph.py`.

The new projection:

- reuses the existing pure `PaperKnowledge` graph mapper and never writes to the Knowledge Graph;
- includes scientific claim nodes only when a normalized evidence record for that source claim has an explicit `eligible_for_publication` decision;
- fails closed when no publication decision exists, even if a raw claim provenance status says `accepted` or `corrected`;
- retains source-document structure such as publication, sections, evidence spans, references, figures and tables;
- retains measurements only when their own provenance review status is `accepted` or `corrected`;
- suppresses free-standing `documented_by` taxon edges produced solely by unreviewed entity extraction;
- allows a taxon entity when it is independently reviewed or participates in an explicitly publication-eligible claim;
- adds `about_taxon` edges from publication-eligible scientific claims to exact canonical taxon identities;
- adds `measurement_of` edges from reviewed measurements to exact canonical taxon identities;
- never authors, fuzzy-matches or activates taxonomy nodes.

### Scientific-method vocabulary

Registered `about_taxon` as a first-class `scientific_method` relationship. Existing `measurement_of` semantics remain first-class. This lets graph traversal express structures such as:

`taxon <- about_taxon - result <- reports_result - publication`

and

`taxon <- measurement_of - measurement <- has_measurement - publication`.

### Read-only live preview bridge

Added `app/calyx_conversation/scientific_method_graph_preview.py`.

For canonical `LITERATURE_DOCUMENT` ids it:

1. reverse-resolves the canonical source binding;
2. reloads the `PaperKnowledge` extraction bundle;
3. revalidates immutable source hash and evidence-anchor integrity;
4. resolves extracted taxon names only by exact active `oc_graph.kg_nodes.display_label` matches;
5. builds the strict publication-eligible graph projection;
6. returns node/edge counts, node/edge type coverage, omitted-candidate counts and exact taxon-resolution counts;
7. performs no graph mutation and no review-state mutation.

The existing Calyx literature search now invokes this preview for research-document corpus results, alongside the already implemented publication-eligible normalized-evidence bridge. The graph-literature governed context therefore carries both the reviewed scientific evidence and a preview of how that evidence would connect into scientific-method graph structure.

## Validation coverage

Added `tests/test_publication_eligible_paper_graph.py` covering:

- publication decision required for claim materialization;
- reviewed-but-not-publication-eligible claims are omitted;
- publication-eligible claims connect to canonical taxon nodes through `about_taxon`;
- reviewed measurements connect through `measurement_of`;
- no publication decisions fail closed;
- unreviewed taxon entities cannot create free-standing `documented_by` relationships.

The dedicated `CALYX KG Bulk Source Validation` workflow now compiles and tests the strict graph projection, scientific-method vocabulary, preview bridge, reviewed extraction bridge, research-document fallback, occurrence query, providers and existing graph materialization paths.

### Exact-head validation state

At exact head `14fbc0f27c648df5249dc68afa5eef227d962f96`, GitHub created `CALYX KG Bulk Source Validation` run `31611617521`, but the only `validate` job completed with `steps=null` and no logs. Therefore checkout, dependency installation, Python compilation, pytest, Ruff and diff hygiene did not execute. This is recorded as runner/infrastructure non-execution, not as a code-test failure and not as successful validation.

No validation claim in this Brain record treats a zero-step GitHub job as executable evidence.

## Governance boundary

This implementation deliberately stops before production graph publication. The preview is read-only. Publishing the resulting reviewed scientific-method nodes and edges into production `oc_graph` is a graph mutation and remains subject to the existing explicit publication/owner governance boundary.

## Next operational gate

1. obtain executable exact-head validation;
2. run bounded live read-only acceptance against real canonically bound literature extractions;
3. inspect resulting node/edge coverage and exact taxon resolution;
4. only then consider a separately governed production publication slice.
