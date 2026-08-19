# CALYX-TIG-006 — Europe PMC Molecular Candidate Harvester

## Purpose

TIG-005 created a governed molecular evidence candidate store but deliberately left it empty. TIG-006 adds a bounded acquisition path from real scientific literature into that review queue without weakening the evidence boundary.

## Source

The first external source is Europe PMC. Its Articles REST API supplies publication metadata and abstracts; its Annotations API supplies text-mined gene/protein annotations. Europe PMC documents `annotationsByArticleIds` as the article-scoped annotations endpoint and supports `Gene_Proteins` annotations supplied by the Europe PMC provider.

No Europe PMC annotation is treated as a validated Orchid Continuum scientific conclusion. It is only one ingredient in candidate detection.

## Candidate gate

A paper can generate a TIG molecular candidate only when one abstract sentence contains all of the following:

1. the configured canonical orchid target (the harvester is invoked with an explicit canonical taxon ID and scientific name);
2. a Europe PMC gene/protein annotation;
3. a controlled orchid trait phrase;
4. an explicit association/relation phrase.

Article-level co-occurrence is insufficient. A paper that mentions a gene in one sentence and a trait elsewhere does not generate a candidate.

## Controlled trait surface

The first vocabulary covers flower color/pigmentation, floral scent/volatiles, spur length, flowering time/anthesis, floral morphology, and pollinator-mediated floral traits. This is intentionally narrow. Additional traits should be added only with explicit tests and vocabulary review.

## Association typing

Statements containing expression/transcript language are staged as `expression_association`; selection/QTL/locus language is staged as `selection_association`; other explicit gene–trait relation sentences are staged as `genetic_association`.

Europe PMC entity URIs are preserved in provenance. Clear UniProt identifiers are retained as protein identifiers; clear gene-system URIs are retained as gene identifiers; otherwise the annotated gene/protein name is retained as a named molecular marker rather than inventing an identifier.

## Governance

All harvested records are written to `oc_genomics.molecular_evidence_candidates` with the existing default `review_state='candidate'`. They are not visible through the accepted-only live TIG views until explicit human review changes the state to `accepted`.

The harvester never:

- accepts a candidate automatically;
- creates a causal claim;
- publishes to the Knowledge Graph;
- publishes to Zenodo;
- converts raw sequence presence into trait association evidence.

## Idempotency and bounds

Candidate IDs are the deterministic TIG-005 SHA-256-derived IDs. Re-running the same evidence upserts the same candidate rather than multiplying records. Each run is bounded to at most 100 requested taxa and at most 100 Europe PMC search results per taxon.

## Operator command

Dry run:

```bash
python scripts/calyx_tig_europepmc_harvest.py \
  --target 'CANONICAL_TAXON_ID=Scientific name' \
  --page-size 25 \
  --dry-run
```

Persist candidates to Neon/Postgres after inspecting a dry run:

```bash
python scripts/calyx_tig_europepmc_harvest.py \
  --target 'CANONICAL_TAXON_ID=Scientific name' \
  --page-size 25
```

Persistence requires the existing `DATABASE_URL`. No new secret is required for Europe PMC public API access.

## Next work

1. bind harvest targets automatically to the canonical World Plants taxon surface rather than requiring explicit operator IDs;
2. add literature-extraction handoff so full-text evidence bundles can propose the same candidate contract;
3. add curated molecular database adapters (NCBI Gene/GenBank/SRA, UniProt, GO/pathways) while preserving source-version provenance;
4. add review-queue list/filter endpoints before any larger acquisition run.
