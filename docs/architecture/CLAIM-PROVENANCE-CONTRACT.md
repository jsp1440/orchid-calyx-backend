# Claim-Level Provenance Contract (`oc-claim-provenance-v1`)

**Module:** `runtime/knowledge_graph/claim_provenance.py`
**Consumer:** the graph-grounded reasoning pilot (`app/graph_grounded_reasoning/retrieval.py`)
**Stacked on:** #1829, which is stacked on #1819
**Producers (proposed, not changed here):** the #901 paper-graph materializer and the 088c assertion publisher

## Why

The audit for #1819 found the following.

**No graph producer records claim-level provenance:**
- Legacy domain adapters write `payload={}` on every edge (`runtime/knowledge_graph/adapters.py`).
- The 088c assertion publisher stores only `publication_id`, `publication_version`, `assertion_id` and `assertion_version` on graph payloads (`app/knowledge_publication/graph_mapping.py`).
- Its `graph_provenance_links` rows leave `interpretation_id` and `evidence_packet_id` NULL (`graph_postgres_repository._provenance`).
- Anchors reach those rows only as unstructured JSON.

**#901** carries page and character spans, but only on separate `evidence` nodes. Its claim nodes hold method and confidence in the generic `evidence_class` and `confidence_*` columns.

**The reader side:** the #1819 pilot read flat edge keys that no producer emits. On real graph data it would therefore abstain on every edge.

## The contract

There is **one nested payload key**, `claim_provenance`, on an existing graph object:
- `oc_graph.kg_edges.payload_json` or `kg_nodes.payload_json` for domain publishers, including #901;
- `oc_knowledge_publication.graph_object_versions.payload` for the 088c publisher.

There is no new table, store, schema migration or graph engine.

```json
{
  "contract_version": "oc-claim-provenance-v1",
  "assertion_id": "claim-7",
  "source": {"document_id": "paper-9", "revision_id": "paper-9@r2", "content_hash": "<sha256>"},
  "anchors": [{"page_start": 4, "page_end": 4, "char_start": 100, "char_end": 180, "anchor_id": "ev-1"}],
  "taxon": {"canonical_name": "Exemplaria aurea", "link_status": "accepted",
            "taxonomy_release": "<World Plants release>", "node_key": "taxon:101", "authority": "world_plants"},
  "extraction": {"method": "model_extracted", "extractor": "…", "extractor_version": "…"},
  "confidence": 0.7, "confidence_is_probability": false,
  "uncertainty": [],
  "review_status": "unreviewed",
  "qualifiers": [],
  "lineage": {"conflicting_assertion_ids": [], "interpretation_ids": [],
              "evidence_packet_ids": [], "normalized_record_ids": []}
}
```

**Shared vocabularies.** `extraction.method` and `review_status` are read from `app.literature_extraction.models.Provenance` at import time, so they cannot drift.

**Taxon fields.** `taxon.link_status` uses the #1810 taxon-link vocabulary that `canonical_graph_mapping` (#1829) emits. Only `accepted` and `synonym` are valid.

**Validation** (`parse_claim_provenance`) fails closed and names every violation. It refuses a record when:
- **Source:** the source document is undeclared.
- **Anchor:** no anchor has a page, character span or structured locator; or a page or character range is inverted.
- **Taxon:** the taxon is unbound, its authority is not World Plants, or its link is not verified.
- **Extraction and review:** the extraction method or review status is unknown, or the claim was rejected in review.
- **Confidence:** confidence is out of [0, 1]; or there is neither a confidence nor an explicit uncertainty; or the record claims `confidence_is_probability`.
- **Identity:** the assertion ID is missing.
- **Locality:** any locality or coordinate key appears anywhere in the record.

**Producer helper.** `from_literature_claim(claim, evidence, …)` builds a record from `app.literature_extraction` `Claim` and `Evidence` dumps. Anchors come only from the evidence the claim cites. The record still has to pass validation before a publisher stores it.

**Audit helper.** `coverage(payloads)` reports how many graph objects carry valid provenance, with counts per violation.

## What the pilot now does

For each one-hop edge, the pilot does the following:
1. It parses `claim_provenance`. Any other edge payload key is ignored.
2. It **cross-checks** the declared source against the literature index, through the existing document-scoped `RetrievalEngine` lookup. The declared revision and content hash must match what the index holds; otherwise the result is `SOURCE_REVISION_MISMATCH`.
3. It requires the claim's taxon to be the resolved accepted taxon and its node; otherwise the result is `TAXON_BINDING_MISMATCH`.
4. It surfaces extraction method, confidence (never as a probability), declared uncertainty and taxon binding on every packet item.
5. It adds `MODEL_EXTRACTED_ASSERTIONS` and `DECLARED_SOURCE_UNCERTAINTY` uncertainty markers.

Only items that pass every check can be cited. Every other item stays visible in the packet, with its anchor state and violations.

The synthetic benchmark fixture was migrated to this contract, and its results are unchanged.

## Proposed producer integration

Not implemented here; it belongs to the owning lanes.

| Producer | Change | Where |
|---|---|---|
| #901 `paper_knowledge_graph` / `publication_eligible_paper_graph` | Attach `from_literature_claim(...).to_payload()` under `claim_provenance` on claim nodes and on `about_taxon` and interaction edges. Bind `taxon` from `canonical_graph_mapping`, not from a caller-supplied name map. | #901 branch (`feature/calyx-kg-materialization-current-main`), which is conflicted with `main` |
| 088c `AssertionGraphMapper` | Merge `claim_provenance` into the `qualified_assertion` node payload, built from the trusted snapshot's provenance roots and anchors plus `scientific_scope`. | `app/knowledge_publication/graph_mapping.py` |
| 088c `GraphPostgresRepository._provenance` | Fill the existing `interpretation_id` and `evidence_packet_id` columns, which are written NULL today. | `app/knowledge_publication/graph_postgres_repository.py` |
| Pilot | Read the 088c two-hop shape (subject → `HAS_ASSERTION` → assertion) as well as one-hop edges. | `app/graph_grounded_reasoning/retrieval.py` (next slice) |

None of these changes requires a migration. Publication stays human-review-governed: a valid `claim_provenance` record is a precondition for citation, not authority to publish.
