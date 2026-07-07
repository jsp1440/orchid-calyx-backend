# BUILD-MEDIA-001 — Backend Evidence

## Implemented endpoint

`GET /api/media/genus/{genus}?limit=12`

The endpoint is served by Calyx through `app/routers/orchid_widgets.py`.

## Data path

`Calyx → oc_widget.v_genus_of_day_cards → taxon-linked hero_image records`

The endpoint does not call iNaturalist, GBIF, Plantae, Wikimedia, or any other external-provider API. It only returns media URLs already present in the Orchid Continuum widget view.

## Server-side safeguards

- normalizes and validates genus input;
- requires a taxon identifier and accepted scientific name;
- rejects missing/non-HTTP URLs;
- rejects obvious herbarium/specimen, illustration/plate, document, scan, and archive URL patterns;
- uses deterministic accepted-name/taxon-ID ordering;
- returns an honest `no_approved_media` state rather than substituting another image.

## Deployment verification required

This branch has not been deployed. The acceptance set must be called against the deployed Calyx service after review:

- Cattleya
- Dracula
- Dendrobium
- Bulbophyllum
- Vanilla

For each call, record the returned item count, scientific names, source names, exclusions, and status. No claim of live results is made in this branch.

## Known data limitation exposed by this implementation

`oc_widget.v_genus_of_day_cards` exposes `hero_image`, taxonomy identity, accepted name, image count, and collection tag, but does not expose canonical source-record URL, license, or underlying image quality score. The endpoint therefore returns those fields as `null` until the widget view is extended from the source image tables.
