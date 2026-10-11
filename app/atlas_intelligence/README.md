# Atlas Intelligence Module

This module is the governed foundation for Atlas Earth Systems, thematic cartography, reasoning, and reproducibility.

## Primary entry point

```python
from app.atlas_intelligence import build_vertical_slice

result = build_vertical_slice()
manifest = result["manifest"]
reasoning = result["reasoning"]
brain_records = result["brain_records"]
```

## Invariants

- Spatial datasets require explicit CRS, extent, source version, license, attribution, and checksum.
- Biodiversity layers require resolved taxon identity.
- Time-dependent layers require temporal coverage.
- Thematic manifests are deterministic for identical ordered inputs.
- Reasoning distinguishes observation, inference, uncertainty, and unavailable data.
- Inference requires supporting layers and confidence.
- Unsupported causal language is rejected.
- Brain records carry durable IDs, aliases, lifecycle state, relationships, provenance URI, and checksum.
- No contract in this module authorizes publication, deployment, or production graph mutation.

## Atlas Explorer API (`explorer.py`, `occurrences.py`, `locality.py`)

Read-only, public-safe routes under `/atlas`:

| Route | Contract | Purpose |
|---|---|---|
| `GET /atlas/occurrences/query` | `oc-atlas-occurrence-query-v1` | Viewport (`bbox`, `zoom`) query returning locality-safe points or grid clusters; taxon, year, month, basis-of-record filters; keyset `cursor`; `limit` ≤ 2000. |
| `GET /atlas/occurrences/summary` | `oc-atlas-occurrence-summary-v1` | Year / month / basis-of-record / taxon / genus buckets and dataset attribution for a view. |
| `GET /atlas/taxa/search` | `oc-atlas-taxon-search-v1` | Canonical taxon IDs (`public.orchid_taxonomy.id`) by name. |
| `GET /atlas/catalog/layers` | `oc.atlas-layer-catalog.v1` | Operational vs planned/blocked thematic layers, with blockers. |
| `GET /atlas/capabilities` | `oc.atlas-module-capabilities.v1` | Module capability contracts plus live availability where this process can check it. |

### Source configuration (owner-governed)

No occurrence relation is assumed. Until the owner sets `ATLAS_OCCURRENCE_RELATION`
(a `schema.name` relation) and `DATABASE_URL`, every occurrence route answers with
`source.state = "source_not_configured"` and zero records. Nothing is substituted.

The relation must expose these columns (snake_case Darwin Core); `describe()` verifies
them before any query and reports missing columns as `unavailable`:

`occurrence_id` (internal surrogate key — not a provider key that resolves to a site),
`taxon_id`, `scientific_name`, `genus`, `decimal_latitude`, `decimal_longitude`,
`coordinate_uncertainty_in_meters`, `country_code`, `year`, `month`, `event_date`,
`basis_of_record`, `dataset_name`, `institution_code`, `license`, `rights_holder`,
`references_uri`, `iucn_category`, `conservation_status`, `assessment_resolved`, `locality`.

Set `ATLAS_OCCURRENCE_USE_POSTGIS=true` when the relation also has an indexed
`geom geometry(Point, 4326)` column; otherwise a `(decimal_latitude, decimal_longitude)`
B-tree index is the recommended access path.

### Locality invariants

- Every point passes through `locality.resolve_location(..., access="public")`, a port of
  the frontend's `atlasLocalitySafety.ts`; `contracts/atlas_locality_policy_vectors_v1.json`
  holds parity vectors generated from the TypeScript implementation.
- Free-text locality, full event date, and `references` are withheld whenever a threat or
  precaution cell applies.
- Clusters are built from generalised positions; the SQL aggregate path only runs for
  whole-degree cells (which nest every policy cell) and positions clusters at cell centres.
