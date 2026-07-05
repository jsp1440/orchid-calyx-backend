# BUILD-040 — Genus Experience Backend Rebuild

## Objective

Stop patching the old Featured Genus / Genus of the Day image pathway and begin rebuilding it around a single contract:

> Featured Genus public data must come from Orchid Continuum database tables, not iNaturalist fallback.

## Implemented

### New OC-only genus experience router

Added:

- `app/routers/genus_experience.py`

The new router builds a genus payload from Orchid Continuum database tables only. It is designed to provide one payload that can eventually drive the Featured Genus hero, gallery, habitat, pollinator, mycorrhizal, climate, and relationship panels.

Current endpoint implementation:

- species from `public.taxonomy_species`
- images from `public.orchid_images`, falling back only to `public.oc_eol_orchid_images`
- habitat summaries from `public.oc_species_habitat_claims`
- relationship availability counts from:
  - `public.oc_occurrences`
  - `public.advanced_orchid_pollinator_relationships`
  - `public.orchid_fungus_associations`
  - `public.oc_species_habitat_claims`
  - `public.species_climate_profile_monthly`

The response explicitly includes:

- `source: "Orchid Continuum database only"`
- `uses_inaturalist: false`

### Mounted through existing widgets router

Updated:

- `app/routers/orchid_widgets.py`

Added:

- `GET /api/widgets/genus-experience/{genus}`

This delegates to the new backend implementation without requiring a risky edit to `app/main.py` in this build.

## What this does not finish yet

This build starts the rebuild but does not yet complete the public frontend replacement. The next step is to point the frontend Featured Genus experience at this endpoint, remove iNaturalist fallback from the public Featured Genus pathway, and then verify real database images and relationship counts.

## Deployment

Backend deployment required.
