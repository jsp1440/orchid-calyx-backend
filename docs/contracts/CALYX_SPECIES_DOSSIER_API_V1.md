# Calyx Species Dossier API v1

Status: implementation contract
Owner: Orchid Continuum backend
Brain source: `CALYX_FEDERATED_SPECIES_DOSSIER_V1`

## Purpose

Provide one canonical, evidence-preserving species dossier and Atlas service used by Featured Genus, Atlas, Identification Matrix, Calyx, University, Research Station, Conservatory, and federation partners.

## Canonical identity

Every response is keyed by stable `taxon_id`. Incoming names and synonyms are resolved before dossier assembly. Display binomial and full scientific name are separate fields.

## Evidence states

Every section and Atlas layer must declare one of:

- `available`
- `provisional`
- `conflicting`
- `modeled`
- `inferred`
- `unavailable`

Missing evidence is never represented as zero or as a generic genus-level statement.

## Dossier endpoint

`GET /api/platform/species/{taxon_id}/dossier`

Required top-level fields:

- `contract_version`
- `taxon_id`
- `display_name`
- `full_scientific_name`
- `accepted_name`
- `identity`
- `nomenclature`
- `protologue`
- `type_material`
- `historical_media`
- `living_media`
- `morphology`
- `distribution`
- `atlas_summary`
- `ecology`
- `phenology`
- `pollinators`
- `mycorrhizae`
- `conservation`
- `literature`
- `cultivation`
- `knowledge_graph`
- `calyx_narrative`
- `research_gaps`
- `identification_matrix`
- `related_species`
- `external_partners`
- `provenance`
- `freshness`
- `unavailable_sections`

## Atlas endpoint

`GET /api/platform/species/{taxon_id}/atlas`

Layer contract:

- occurrence points
- countries and regions
- elevation
- flowering time
- habitat and ecoregion
- climate
- pollinator evidence and routes only where supported
- fungal evidence
- protected areas
- threats and conservation
- dated historical records
- modeled or inferred historical range where explicitly labeled

Every point or feature includes source, observed date, coordinate uncertainty, taxonomic name used, current accepted taxon, evidence state, provenance, and license where applicable.

## Federation resolver

`GET /api/platform/federation/resolve-species`

Accepted inputs:

- `taxon_id`
- `name`
- `source_url`
- `partner`
- `slug`

Resolution states:

- `resolved`
- `ambiguous`
- `unresolved`
- `invalid`
- `partner_not_authorized`

Resolved responses return the canonical dossier and Atlas URLs plus a reciprocal partner return URL when registered.

## Partner registry

Partner permissions remain separate for:

- outbound linking
- indexing metadata
- quoting text
- displaying images
- extracting diagnostic traits
- API access

Public partner links contain no secrets. Signed widget credentials and API credentials are revocable, domain-scoped, and never embedded as unrestricted reusable secrets.

## Dependencies

- graph-readiness service
- canonical species evidence packets
- Calyx species narrative contract
- current taxonomy and synonym resolver
- Atlas occurrence and layer services
- Identification Matrix contracts

## Safety

No endpoint grants publication authority, partner reuse permission, verified-image identity, graph mutation, or deployment authority.
