# ADR-ATLAS-001 — Earth Systems and Thematic Cartography Are Core Atlas Capabilities

Status: Accepted
Date: 2026-08-06
Decision owner: Jeffery Parham

## Context

A conventional occurrence map cannot explain orchid distributions, environmental constraints, temporal change, conservation gaps, or survey priorities. The Orchid Continuum requires an Atlas that integrates biodiversity evidence with geology, soils, hydrology, terrain, climate, remote sensing and environmental change. It also requires repeatable, publication-ready thematic map generation that does not depend on manual GIS reconstruction.

## Decision

The Atlas will include two first-class governed engines:

1. **Earth Systems Engine** — versioned environmental layers and analyses covering geology, soils, hydrology, topography, climate, remote sensing and environmental change.
2. **Thematic Map Engine** — deterministic generation of interactive, static, print, journal and educational map products from versioned map specifications.

Both engines will operate through provenance, licensing, uncertainty, review and publication-control boundaries. They will register architecture, decisions, dependencies, implementation status and reproducibility manifests with the Brain.

## Consequences

### Positive

- environmental explanations become possible rather than merely spatial display
- conservation and survey analyses become reproducible
- maps can be regenerated when source data changes
- cartographic outputs can be reused across the Atlas, Knowledge Explorer, Research Station, University and reports
- engineering work becomes searchable and discoverable through Brain records

### Costs and risks

- large datasets and spatial processing requirements
- scientific uncertainty can be obscured by attractive maps
- source licensing and attribution must be enforced
- scale, projection and classification choices can materially affect interpretation
- causal claims require stronger evidence than spatial correlations

## Guardrails

- no unsupported causal language
- no silent taxonomic or coordinate resolution
- no publication from unlicensed or unreviewed data
- no map without a machine-readable manifest
- no analysis without source versions, CRS, temporal extent and uncertainty metadata
- no autonomous merge, deployment or production publication

## Alternatives rejected

- Atlas as a frontend-only map viewer
- manual GIS production without reproducibility manifests
- combining all environmental data into one unversioned layer
- allowing generative AI to invent geographic boundaries, values or scientific conclusions
