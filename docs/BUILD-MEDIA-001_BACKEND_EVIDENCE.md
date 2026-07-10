# BUILD-MEDIA-001 — Backend Evidence

## Implemented endpoint

`GET /api/media/genus/{genus}?limit=12`

The endpoint is served by Calyx through `app/routers/orchid_widgets.py`.

## Authoritative data path

`Calyx → public.orchid_taxonomy → public.orchid_images`

The resolver does **not** use the legacy `oc_widget.v_genus_of_day_cards.hero_image` field. That legacy field was the wrong path because it could preserve the iNaturalist-derived hero behavior this build replaces.

The endpoint is read-only and makes no external-provider API calls. It returns image records already linked to canonical Orchid Continuum taxonomy rows.

## Server-side safeguards

- validates and canonicalizes the requested genus;
- verifies that the genus exists in `public.orchid_taxonomy`;
- requires a linked taxonomy ID, image URL, and source name;
- excludes duplicate records;
- excludes iNaturalist-source records for Featured Genus;
- excludes obvious herbarium/specimen, illustration/plate, document, scan, and archive patterns using URL, type, description, and alt-text fields;
- returns available source, image-license, rights-holder/observer attribution, and GBIF occurrence record links;
- returns an honest `no_approved_media` state rather than substituting another orchid.

## Known data condition

The canonical image table exposes `image_source`, `image_license`, `image_rights_holder`, `observer_name`, `gbif_occurrence_key`, `image_type`, `image_description`, and `alt_text`. It does not expose a single existing universal quality score or approval flag for this dataset. This build therefore does not invent one; it uses transparent provenance plus exclusion filters.

## Deployment verification required

This branch has not been deployed. After review, call the deployed Calyx endpoint for:

- Cattleya
- Dracula
- Dendrobium
- Bulbophyllum
- Vanilla

For each genus, record exact returned item count, scientific names, image-source names, licenses/attributions where present, exclusion summary, and endpoint status. No claim of live results is made in this branch.
