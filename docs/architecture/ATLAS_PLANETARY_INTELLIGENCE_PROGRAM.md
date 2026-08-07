# Atlas Planetary Intelligence Program

Status: Approved implementation program
Owner: Atlas Director autonomous lane
Repository: `jsp1440/orchid-calyx-backend`

## Mission

Build the Orchid Continuum Atlas as a governed planetary biodiversity and Earth-systems intelligence engine rather than a map viewer. The Atlas must explain where orchids occur, why they occur there, how conditions change through time, and how evidence can be transformed into repeatable thematic maps and conservation analyses.

## First-class engineering domains

1. Spatial foundation and layer registry
2. Biodiversity distribution and range intelligence
3. Earth systems: geology, soils, hydrology, topography, climate, remote sensing, land-use and environmental change
4. Conservation intelligence and prioritization
5. Ecological interaction mapping
6. Temporal and 4D analysis
7. Atlas reasoning and sampling-gap analysis
8. Thematic cartography and report generation
9. Mission Control operations and review queues
10. Brain documentation, semantic discovery, and reproducibility

## Autonomous engineering organization

### Atlas Director

Coordinates the backlog, selects bounded implementation slices, reports blockers, and opens draft PRs. It may not self-approve scientific conclusions, publish production layers, or merge its own work.

### Core specialist lanes

- Geospatial Infrastructure Engineer
- Biodiversity Mapping Engineer
- Earth Systems Engineer
- Geology Engineer
- Soil Science Engineer
- Hydrology Engineer
- Topography Engineer
- Climate Intelligence Engineer
- Remote Sensing Engineer
- Environmental Change Engineer
- Conservation Intelligence Engineer
- Ecological Interaction Engineer
- Temporal Atlas Engineer
- Thematic Map Engineer
- Cartography Engineer
- Atlas Reasoning Engineer
- Brain Architect / Knowledge Librarian

## Core records

All Atlas outputs must use versioned, provenance-bearing records for:

- spatial dataset
- layer definition
- source and license
- coordinate reference system
- geographic extent
- temporal extent
- resolution and scale
- processing lineage
- taxonomic resolution
- uncertainty
- validation status
- review status
- publication status
- map specification
- map artifact
- analysis run
- reasoning claim and evidence

## Earth Systems Engine

The Earth Systems Engine provides explanatory environmental context. It must support:

- bedrock, lithology, geological age, volcanism, tectonics and parent material
- soil class, pH, texture, organic matter, drainage, salinity, moisture and nutrient proxies
- watersheds, wetlands, rivers, groundwater, fog and water availability
- elevation, slope, aspect, curvature, terrain ruggedness and solar exposure
- temperature, precipitation, humidity, VPD, cloud, wind, frost, drought and climate anomalies
- vegetation indices, canopy, fire, deforestation, fragmentation and land-use change

No environmental association may be presented as causal without supporting evidence and an explicit reasoning status.

## Thematic Map Engine

The engine converts a governed map specification into reproducible artifacts.

### Required map specification fields

- question and intended audience
- geographic and temporal extent
- input layers and versions
- filters and thresholds
- aggregation method
- uncertainty treatment
- projection selection and rationale
- classification method
- legend specification
- accessibility requirements
- citation and provenance block
- export formats

### Initial map families

- species and genus distributions
- richness, endemism, rarity and sampling density
- protected-area overlap and conservation gaps
- geology, soils, hydrology, climate and terrain
- pollinators, fungi, host trees and ecological interactions
- collection history, temporal change and phenology
- habitat suitability and climate refugia
- research effort and survey priorities

### Outputs

- interactive web map payload
- static SVG and PNG
- print-ready PDF-ready layout payload
- journal-figure layout
- educational simplified map
- machine-readable map manifest

## Brain capture rule

No Atlas feature is complete until it produces searchable Brain records for:

1. architecture object
2. decision record
3. ontology changes
4. dependency graph changes
5. implementation status
6. validation evidence
7. reproducibility manifest
8. supersession history

Every record must have a durable identifier and semantic keywords. Superseded records are preserved rather than deleted.

## Phased implementation

### Phase A — Architecture and contracts

- inspect current spatial, occurrence, taxonomy, graph and publication-control code
- define versioned schemas for datasets, layers, map specifications, analysis runs and artifacts
- define candidate, reviewed and published states
- define Earth-systems adapters and failure boundaries
- define deterministic thematic-map assembly
- create ADRs and Brain registration payloads

### Phase B — Executable vertical slice

Use fixture data to demonstrate:

- one orchid taxon distribution
- one Earth-science layer
- one conservation layer
- one sampling-effort layer
- one reproducible thematic map manifest
- one Atlas reasoning response that distinguishes observation, inference and unknown
- validation that fails closed when provenance, CRS, license, taxonomic identity or publication permission is absent

### Phase C — Integration

- Knowledge Graph handoff
- Literature evidence links
- AI.Vision and media links
- Knowledge Explorer links
- Research Station analysis workspace
- protected APIs
- Mission Control status and review queues

### Phase D — Production readiness

- real data adapters
- caching and spatial indexing
- performance tests
- audit logs and rollback
- accessibility and cartographic review
- real-world validation corpus
- deployment controls

## Acceptance criteria for the first implementation PR

- architecture and ADR committed
- executable contracts or schemas added using established repository conventions
- fixture-backed vertical slice
- deterministic map manifest generation
- uncertainty and provenance preserved
- Earth-science and biodiversity layers remain independently versioned
- tests reject missing provenance, CRS, license, broken layer references, invalid publication transitions and nondeterministic assembly
- compile, lint and focused tests pass
- draft PR only
- no production graph mutation, automatic publication, deployment or self-merge
