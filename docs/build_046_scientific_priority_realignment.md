# BUILD-046: Calyx Scientific Priority Realignment

BUILD-046 rebalances the running Calyx autonomous loop toward orchid conservation science. It does not redesign the runtime and does not remove judging or awards. Those modules remain available as optional low-priority work.

## Priority Model

Scientific modules now lead the mission queue:

- `pollinator_relationships`: 100
- `mycorrhiza_relationships`: 98
- `literature_extraction`: 96
- `ecological_relationship_graph`: 95
- `traitbank_traits`: 94
- `conservation_habitat`: 93
- `image_species_evidence`: 90
- `frontend_knowledge_graph_integration`: 88
- `calyx_core_health`: 80
- `judging`: 25
- `awards`: 20

Judging and awards are lower priority because the core Orchid Continuum mission is conservation science: relationship evidence, fungal and pollinator interactions, literature-backed traits, habitat, conservation, images, and frontend knowledge graph readiness.

## Seeded Scientific Missions

`POST /api/runner/run-once` seeds non-destructive scientific audit jobs first:

- `audit_missing_pollinator_data`
- `audit_missing_mycorrhizal_data`
- `audit_literature_extraction_coverage`
- `audit_traitbank_trait_coverage`
- `audit_ecological_relationship_graph_gaps`
- `audit_frontend_relationship_cards`
- `audit_image_species_evidence_coverage`
- `audit_conservation_habitat_gaps`

Calyx core health remains support work. Judging and awards seed only when no higher-priority scientific job is pending or running.

## Runtime Behavior

`POST /api/runner/execute-next` orders pending jobs by the BUILD-046 priority model before falling back to job id. This means scientific missions run before judging and awards even if lower-priority jobs already exist in the queue.

No destructive actions are introduced. The runtime still executes one queued job per autonomous cycle.

## Provenance and Safety

Scientific audit outputs are coverage audits, not biological facts. Each result includes:

- `source`
- `provenance`
- `confidence`
- `claim_type`
- `review_status`
- `citation`
- `claims`
- `unsupported_claims_promoted=false`

Biological relationship claims must remain unreviewed placeholders until backed by curated evidence, source tables, or citations.

## Frontend Alignment

No frontend changes are part of BUILD-046. A future frontend/control-panel build should consume backend-backed evidence structures for:

- Pollinator cards: `pollinator_relationships` mission output and future relationship endpoints with source/citation fields.
- Mycorrhiza cards: `mycorrhiza_relationships` output and `oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache`-backed evidence.
- Relationship graph: `ecological_relationship_graph` output and graph endpoints/tables with explicit edge provenance.
- Literature evidence: `literature_extraction` mission output with citation identifiers and extraction review status.
- Conservation/habitat summaries: `conservation_habitat` output with source and review metadata.
- Image/species evidence: `image_species_evidence` output with image/specimen/source attribution.

## Verification

After deployment:

1. `GET /api/runner/autonomous-status` confirms runtime remains enabled/running.
2. `GET /api/runner/summary` shows scientific modules above judging and awards.
3. `POST /api/runner/run-once` seeds scientific missions without duplicate active missions.
4. `POST /api/runner/autonomous-cycle` executes the highest-priority pending scientific mission.
5. `GET /api/runner/summary` shows scientific jobs ordered above judging and awards.
