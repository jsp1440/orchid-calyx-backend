# BUILD-064 Deliverable 2 — Climate Validation Report

Read-only. No climate layers computed. No backfill. Verification: 2026-07-15.

## Audited object: `oc_env_intel.species_environment_profile`
- Rows: 26,788 (19,263 project into the KG after backbone filter).
- Build id stamped on rows: `OC-ENVIRONMENTAL-INTELLIGENCE-1A`.

### What the columns actually contain
Occurrence/observation counts, elevation min/max/avg (+record count),
lat/long **bounding box**, country counts + array, first/last observed year,
habitat claim counts, and a qualitative `climate_proxy_zones` array, plus an
`environmental_evidence_score` and readiness labels. Sample rows carry
`evidence_notes` such as *"no verified occurrence coordinates; no elevation
evidence; no habitat evidence"*.

### Characterization
This is an **occurrence-derived environmental summary / proxy**, NOT a climate
dataset. There are **no** modelled climate variables (no temperature,
precipitation, or bioclim indices). Derivation is aggregation over occurrence
records; resolution is "per taxon", update frequency is per environmental-
intelligence build, not a climate data cadence.

Classification: **environmental proxy (occurrence-derived), mixed with habitat
summaries** — not true climate, not occurrence-derived *climate* summaries.

## Do real climate datasets exist elsewhere?
Yes by schema, but all are **empty**:
| Table | Nature | Rows |
| --- | --- | ---: |
| `public.species_climate_profile_monthly` | true monthly normals (tmin/tmax/tmean/precip p05/p50/p95) | **0** |
| `public.climate_normals_monthly_point` | point climate normals | **0** |
| `public.culture_engine_species_monthly_climate` | per-species monthly climate | **0** |
| `public.oacs_origin_climate_profiles` | origin climate profiles | **0** |

`species_climate_profile_monthly` has the correct schema for real bioclim-style
data and is the intended home, but **no real climate data is populated in
production today**.

## Conclusion
The climate domain must be classified **BLOCKED**: the connected source is a
proxy that must not be presented as climate, and the authoritative climate
tables are unpopulated. No computation or backfill was performed (out of scope).
