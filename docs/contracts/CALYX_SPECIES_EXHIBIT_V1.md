# Calyx Species Exhibit Contract v1

Public target: `GET /api/platform/homepage/genus/{genus}/species-exhibit?limit=9`

The backend must return distinct canonical species, not merely distinct media rows.

Each card contains:
- taxon_id
- display_name
- full_scientific_name
- accepted_name_status
- representative_media with attribution, license, provenance and identification state
- caption
- distinguishing_fact
- evidence_state
- confidence
- provenance anchors
- unavailable_domains
- contradictions and caveats
- species, graph and evidence links

Pipeline:
canonical taxonomy -> species evidence adapters -> Knowledge Graph paths -> contradiction and availability normalization -> Calyx narrative contract -> governed public response.

Rules:
- deduplicate by canonical taxon_id, normalized accepted name and media URL;
- at most one representative card per species;
- missing domains remain unavailable;
- no genus-level text substituted as a species caption;
- no browser scientific scoring;
- no automatic identity verification, graph mutation or scientific publication.