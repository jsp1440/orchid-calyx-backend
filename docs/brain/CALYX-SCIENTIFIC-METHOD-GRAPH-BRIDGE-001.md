# CALYX-SCIENTIFIC-METHOD-GRAPH-BRIDGE-001

## Purpose

Close the integration gap after connecting Calyx to the bulk occurrence corpus and the 6,725-document research corpus: reviewed literature extraction must become graph-shaped scientific evidence rather than remaining a disconnected JSON artifact.

## Problem identified

`PaperKnowledge` already models paper structure, entities, measurements, observations, hypotheses, methods, results, interpretations, limitations, recommendations, evidence spans, references, figures and tables. The original graph mapper could represent many of those objects, but its default claim gate relied on raw extraction provenance review status. That is weaker than the literature pipeline's explicit normalized-record `PublicationDecision` contract. It also did not connect eligible claim/measurement nodes directly back to canonical taxon nodes.

## Implemented

### Strict publication-eligible graph projection

Added `runtime/knowledge_graph/publication_eligible_paper_graph.py`.

The projection:

- reuses the existing pure `PaperKnowledge` graph mapper and never writes by itself;
- treats an explicit normalized-record `eligible_for_publication` decision as authoritative for scientific claim inclusion, even when the original model-extracted claim still carries an `unreviewed` raw provenance flag;
- fails closed for every claim without an eligible publication decision;
- carries publication eligibility and the qualifying normalized record ids into claim-node/edge provenance;
- retains source-document structure such as publication, sections, evidence spans, references, figures and tables;
- retains measurements only when their own provenance status is `accepted` or `corrected`, because measurements do not yet have a separate normalized publication-decision object;
- suppresses free-standing `documented_by` taxon edges produced solely by unreviewed entity extraction;
- adds `about_taxon` edges from publication-eligible scientific claims to exact canonical taxon identities;
- adds `measurement_of` edges from reviewed measurements to exact canonical taxon identities;
- never authors, fuzzy-matches or activates taxonomy nodes.

### Exact taxon resolution

Added `runtime/knowledge_graph/exact_taxon_resolution.py` as the shared resolver for literature-derived graph structure. It resolves extracted taxon entities only when exactly one active persisted `taxon` node has a case-insensitive exact display-label match. Zero matches are unresolved and multiple matches are ambiguous; both fail closed. No synonym guessing, fuzzy identification, taxonomy creation or mutation occurs.

### Scientific-method vocabulary

Registered `about_taxon` as a first-class `scientific_method` relationship. Existing `measurement_of` semantics remain first-class. This lets graph traversal express structures such as:

`taxon <- about_taxon - result <- reports_result - publication`

and

`taxon <- measurement_of - measurement <- has_measurement - publication`.

### Read-only live preview bridge

`app/calyx_conversation/scientific_method_graph_preview.py` now follows canonical `LITERATURE_DOCUMENT` bindings, revalidates immutable source hash/evidence anchors, uses the shared exact taxon resolver and builds the strict publication-eligible graph projection. It reports node/edge type coverage, exact/unresolved/ambiguous taxon resolution, omitted ineligible objects and publication-eligible claim counts without mutating graph or review state.

The existing Calyx literature search invokes this preview for research-document corpus results alongside the publication-eligible normalized-evidence bridge. The governed literature context therefore carries both the reviewed scientific evidence and how that evidence would connect into scientific-method graph structure.

### Governed publication materializer

Added `runtime/knowledge_graph/reviewed_literature_materializer.py` and operator `scripts/materialize_reviewed_literature_graph.py`.

The materializer is deliberately read-only by default. For an explicit bounded list of canonical `public.research_documents` ids it:

1. requires exactly one canonical literature-extraction binding for each requested document;
2. reloads the extraction bundle and revalidates source integrity;
3. resolves taxa using the exact active graph resolver;
4. builds the strict publication-eligible scientific-method graph bundle;
5. validates every node type, edge type and external endpoint against the canonical graph vocabulary/current graph;
6. returns a dry-run publication plan without opening a writable graph repository.

Production execution is separately gated. It requires `execute=True` plus exact confirmation token `PUBLISH_REVIEWED_LITERATURE_GRAPH`. An invalid plan is rejected before opening the writable repository. A valid authorized slice uses the canonical `WritablePostgresGraphRepository`, acquires the existing database single-writer graph lock, routes each bundle through canonical `publish_domain`, commits the complete requested slice once, and rolls the complete slice back on any exception or invalid publisher result.

The operator always requires explicit `--document-id` values and remains read-only unless `--execute` and the exact confirmation token are supplied. Therefore it cannot accidentally expand a publication attempt to the complete research corpus.

## Validation coverage

Focused tests now cover:

- explicit publication decisions overriding stale raw claim review flags;
- reviewed-but-not-publication-eligible claims being omitted;
- eligible claim provenance carrying publication record ids;
- claim-to-taxon `about_taxon` and measurement-to-taxon `measurement_of` connections;
- no-publication-decision fail-closed behavior;
- unreviewed taxon entities being unable to create free-standing `documented_by` relationships;
- strict bundles passing the canonical publisher vocabulary/endpoint checks in an in-memory graph;
- exact taxon resolution requiring exactly one active exact display-label match and separately reporting ambiguous/unresolved entities;
- explicit literature document ids being required before planning;
- dry runs never opening a writable graph repository;
- execute mode requiring the exact confirmation before preparation;
- invalid plans being blocked before writable access;
- an authorized valid fake slice acquiring the graph lock and committing exactly once.

The dedicated `CALYX KG Bulk Source Validation` workflow compiles and tests the strict graph projection, exact taxon resolver, governed literature materializer/operator, scientific-method vocabulary, preview bridge, reviewed extraction bridge, research-document fallback, occurrence query, providers and existing graph materialization paths.

### Exact-head validation history

At exact head `14fbc0f27c648df5249dc68afa5eef227d962f96`, GitHub created `CALYX KG Bulk Source Validation` run `31611617521`, but the only `validate` job completed with `steps=null` and no logs. Checkout, dependency installation, Python compilation, pytest, Ruff and diff hygiene therefore did not execute. This remains recorded as runner/infrastructure non-execution, not as a code-test failure and not as successful validation.

No validation claim in this Brain record treats a zero-step GitHub job as executable evidence.

## Governance boundary

The implementation is now ready to plan a real reviewed-literature scientific-method graph publication slice without mutation. Actually invoking the operator with `--execute` would mutate production `oc_graph`; that remains an owner-governed action and has not been performed.

## Next operational gate

1. obtain executable exact-head validation;
2. run a bounded live read-only operator plan against one or more real canonically bound literature documents;
3. inspect source integrity, publication eligibility, exact taxon resolution and node/edge projection;
4. only after those gates, decide whether to authorize a production publication slice.
