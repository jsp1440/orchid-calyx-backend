# BUILD-047 — Orchid Continuum Scientific Integration Package

Repository target: `orchid-calyx-backend`

Status: planning / implementation package

## Purpose

Calyx is now running as an autonomous backend runtime. BUILD-047 should shift the system from recurring placeholder optimization jobs toward meaningful Orchid Continuum scientific operations.

The priority is not judging or awards. Those remain low-priority society-support functions. The main mission is conservation science: pollinators, mycorrhiza, ecological relationships, literature, traits, climate, elevation, taxonomy, images, and species dossiers.

## Constitution and operating agreements

Follow the Orchid Continuum Constitution and CDS-v2 operating agreements:

- GitHub first.
- Code first.
- Inspect the repository before modifying.
- Preserve working runtime behavior.
- Do not redesign the autonomous runtime unless required.
- Prefer small, reversible, auditable changes.
- Do not delete or overwrite data.
- Do not fabricate biological claims.
- All scientific claims must be provenance-first.
- All ecological relationships must carry source, confidence, claim type, and review state.
- Destructive, deploy, merge, delete, overwrite, or external-send actions require approval gates.
- If blocked, implement everything possible, document the blocker, and continue.

## Current verified runtime state

The backend runtime is alive and executing cycles. The summary shows:

- runtime enabled
- runtime running
- thread alive
- autonomous cycle count increasing
- module registry present
- jobs executing successfully

However, the active jobs are still largely placeholder optimization tasks. BUILD-047 must make the running system scientifically useful.

## Scientific priority order

Calyx should prioritize work approximately as follows:

1. Pollinator relationships
2. Mycorrhizal/fungal relationships
3. Literature extraction and evidence capture
4. Ecological relationship graph
5. TraitBank and trait/glossary integration
6. Conservation and habitat
7. Atlas, elevation, climate, and thematic map support
8. Image/species evidence
9. Species, pollinator, and fungal dossier generation
10. Harvester optimization and federation monitoring
11. Calyx core health
12. Judging and awards

Judging and awards should remain available but low priority. They should only run when higher-priority scientific work is absent or explicitly requested.

## BUILD-047 implementation goal

Implement the first useful scientific mission layer for Calyx.

This build should add a durable, non-destructive scientific mission framework that allows Calyx to discover, queue, execute, and report priority scientific work across Orchid Continuum data systems.

Do not attempt to solve all integrations in one pass. Implement the scaffolding and the first safe audits so Calyx can begin operating productively.

## Required capabilities

### 1. Scientific mission registry

Add or extend the module/mission registry to include scientific mission families:

- `pollinator_relationships`
- `mycorrhiza_relationships`
- `literature_extraction`
- `ecological_relationship_graph`
- `traitbank_traits`
- `conservation_habitat`
- `atlas_elevation_climate`
- `image_species_evidence`
- `species_dossiers`
- `harvester_optimization`

Each mission family should expose:

- name
- description
- scientific purpose
- priority
- cadence recommendation
- allowed task types
- risk level
- enabled status
- provenance requirements

### 2. Safe non-destructive seed missions

Add a seed endpoint or extend the existing mission seeding behavior to create safe missions such as:

- identify orchid taxa missing pollinator data
- identify orchid taxa missing mycorrhizal data
- audit literature extraction coverage
- audit TraitBank/trait coverage
- audit glossary coverage
- audit ecological relationship graph gaps
- audit species without climate/elevation summaries
- audit occurrence records missing elevation
- audit Atlas thematic-map readiness
- audit image/species evidence coverage
- audit harvester status and stale harvesters
- audit frontend relationship cards against backend data
- create candidate species dossier queue
- create candidate pollinator dossier queue
- create candidate fungal dossier queue

Avoid duplicate mission creation.

### 3. Priority-aware runtime scheduling

Update the autonomous runtime scheduling so that scientific missions outrank judging and awards.

Expected rough priorities:

- pollinator_relationships: 100
- mycorrhiza_relationships: 98
- literature_extraction: 96
- ecological_relationship_graph: 95
- traitbank_traits: 94
- conservation_habitat: 93
- atlas_elevation_climate: 92
- image_species_evidence: 90
- species_dossiers: 89
- harvester_optimization: 88
- calyx_core_health: 80
- judging: 25
- awards: 20

### 4. Provenance-first result model

Scientific mission results must include fields or a compatible structure for:

- `source`
- `source_url` or citation placeholder
- `dataset`
- `claim_type`
- `subject_taxon`
- `object_taxon` or related entity
- `relationship_type`
- `confidence`
- `review_status`
- `evidence_summary`
- `created_at`
- `updated_at`

If the existing schema already has equivalent fields, reuse them.

### 5. Pollinator audit v1

Implement a safe first pollinator audit. It should not fabricate relationships.

It should identify:

- taxa with no known pollinator relationship in available backend tables
- taxa with relationship placeholders but no citation
- pollinator records missing confidence/review status
- candidate taxa requiring literature extraction

Output should be a mission result or runtime action summary.

### 6. Mycorrhiza audit v1

Implement a safe first mycorrhiza audit.

It should identify:

- taxa with no known fungal relationship
- taxa with fungal relationship but no source/citation
- fungal links missing confidence/review status
- candidate taxa requiring literature extraction or dataset federation

### 7. Literature and evidence audit v1

Implement a safe first literature/evidence audit.

It should identify:

- taxa with no literature claims
- relationship claims lacking citations
- glossary/trait terms that need normalization
- candidate papers or datasets needing extraction if tables exist

### 8. Atlas/elevation/climate audit v1

Implement a safe first geography/climate audit.

It should identify:

- occurrence records missing elevation, if occurrence tables exist
- taxa missing elevation summaries
- taxa missing climate summaries
- thematic map readiness gaps
- stale atlas cache or absent map layers, if present

Do not call external services in this build unless the repository already has a safe internal client for doing so.

### 9. Harvester optimization audit v1

Implement a safe harvester audit that reports:

- known harvesters
- last run time
- last success
- last failure
- records inserted
- whether a harvester appears stale
- whether a harvester appears to be running without useful yield

Do not change harvester schedules destructively. Queue follow-up tasks as `needs_review`.

### 10. Dossier queue v1

Create mission records or candidate queue entries for:

- species dossiers
- pollinator dossiers
- fungal dossiers

A dossier candidate should include:

- entity type
- scientific name or canonical label
- known data coverage
- missing data categories
- priority reason
- review status

### 11. API endpoints

Prefer extending the existing runner API. Add endpoints only if needed.

Potential endpoints:

- `GET /api/runner/scientific-priorities`
- `POST /api/runner/seed-scientific-missions`
- `GET /api/runner/scientific-summary`
- `GET /api/runner/relationship-gaps`

If equivalent endpoints already exist, reuse them.

### 12. Documentation

Update docs with:

- Calyx scientific priority model
- mission families
- seed mission behavior
- provenance requirements
- how to verify runtime prioritization
- how frontend/control-panel should display scientific mission status
- post-deploy test sequence

## Frontend alignment

Do not modify the frontend in this backend build.

Document which backend outputs should later feed:

- pollinator relationship cards
- mycorrhiza cards
- relationship graph
- species dossiers
- pollinator dossiers
- fungal dossiers
- literature evidence panels
- Atlas/elevation/climate thematic maps
- conservation/habitat summaries

## Validation requirements

Run available tests or minimal checks:

- FastAPI app imports successfully
- `/docs` still loads
- autonomous runtime endpoints still exist
- `GET /api/runner/autonomous-status` still reports running after deployment
- `GET /api/runner/summary` shows scientific mission families or seeded scientific missions
- judging and awards no longer dominate the priority order
- no destructive actions introduced

## Post-deploy test sequence

After backend deployment, test in this order:

1. `GET /api/runner/autonomous-status`
2. `GET /api/runner/summary`
3. `POST /api/runner/seed-scientific-missions` if implemented
4. `GET /api/runner/scientific-summary` if implemented
5. `POST /api/runner/autonomous-cycle`
6. `GET /api/runner/summary`

Expected result:

- runtime remains enabled and running
- scientific modules/missions appear
- pollinator/mycorrhiza/literature/atlas/image/harvester audits are represented
- judging and awards are lower priority
- no destructive actions occur

## Pull request title

BUILD-047: Calyx scientific integration mission layer

## Pull request summary

This PR should shift Calyx from placeholder recurring optimization jobs toward provenance-first scientific mission execution. It introduces or documents scientific mission families for pollinators, mycorrhiza, literature, ecological relationships, traits, conservation/habitat, atlas/elevation/climate, image evidence, dossiers, and harvester optimization while keeping judging and awards as low-priority society-support modules.

## Out of scope

- Full frontend implementation
- External API harvesting unless safe clients already exist
- Bulk destructive database migrations
- Unreviewed biological claims
- Automatic deployment without approval
- Treating anecdotal ecological stories as facts without evidence

## Notes

Interesting ecological stories, including fungi/pollinator/forest interactions, should be treated as research questions until supported by literature. Calyx should record them as hypotheses or investigation prompts, not as established facts.
