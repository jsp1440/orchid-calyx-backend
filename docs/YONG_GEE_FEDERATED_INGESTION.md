# Gary Yong Gee federated ingestion

## Purpose

Import the Gary Yong Gee orchid database as a **federated specialist compilation** and attach its descriptive evidence to the existing Orchid Continuum taxonomic spine and Knowledge Graph.

The source is not treated as a competing taxonomy. World Plants (Hassler) remains the canonical OC backbone. Gary Yong Gee is recorded as compiler/curator; underlying publications named in the workbook remain the scientific sources and should be resolved into Literature nodes in later enrichment.

## Source workbook

The September 2026 workbook supplied to Orchid Continuum contains three sheets (`Original extract`, `Chosen`, `Reduced`). The importer defaults to `Chosen`, which retains the stable source `id`, taxonomic presentation fields, botanical descriptions, habitat/distribution/phenology, similar-species notes, references, and website identifiers.

The raw workbook is intentionally **not committed to this public repository**. The code expects an operator-provided local path.

## Pipeline

1. Read the workbook in read-only mode.
2. Preserve stable source record IDs and SHA-256 source-record digests.
3. Derive the full taxon name from `websiteInformalName` (fallback: `websiteFormalName`).
4. Resolve by exact canonical name/synonym against existing OC taxon nodes. No fuzzy name is auto-published.
5. Leave ambiguous/unresolved names in the dry-run report.
6. Project matched descriptive fields into the existing `EVIDENCE_ADAPTER` row contract.
7. Attach evidence nodes to the canonical taxon node through `supported_by_evidence` edges using the existing Knowledge Graph publisher.

## Evidence fields

- nomenclatural publication/year
- etymology
- synonyms/nomenclature
- common name
- section/subsection
- distribution
- habitat/elevation prose
- flowering season/phenology
- scent
- botanical morphology (`characteristicsp`)
- fruit/capsule
- similar-species/diagnostic comparison
- taxon notes
- bibliography/references
- Gary compiler notes

The first import preserves description-level evidence. Subsequent semantic extraction may split morphology into atomic Matrix character assertions while retaining this source lineage.

## Dry run

```bash
python scripts/import_yong_gee_federated.py /secure/path/Yong\ Gee\ data.xlsx \
  --sheet Chosen \
  --report /tmp/yong-gee-reconciliation.json \
  --evidence-jsonl /tmp/yong-gee-evidence.jsonl
```

`DATABASE_URL` must point to the OC database so the command can read canonical taxon nodes. The command never writes to the graph.

The report records totals for matched, ambiguous, and unresolved taxa plus the number of evidence rows ready for controlled publication.

## Publication

`publish_matched_evidence()` deliberately accepts a repository object and delegates to the existing `publish_domain(..., EVIDENCE_ADAPTER, ...)` path. Tests use the in-memory graph. Production publication must be invoked only by the existing authenticated/human-approved graph publication workflow; this importer adds no bypass.

## Attribution/provenance

Every evidence row records:

- `source_name = Gary Yong Gee Orchid Database`
- `source_kind = specialist_compiled_resource`
- source record ID
- deterministic source-record digest
- compiler = Gary Yong Gee
- underlying citation status

Where the workbook includes `referencesp`, the record is marked as containing underlying citations. A later reference-resolution pass should parse these into canonical Literature nodes and replace unresolved citation state with explicit source relationships.

## Matrix relevance

Once published, the Matrix does not query a special Gary database. It queries the same OC taxon node it already uses for images, taxonomy, Atlas, pollination, mycorrhizae, literature, conservation, and other evidence. Gary-derived morphology becomes one more provenance-preserving evidence stream on that taxon.
