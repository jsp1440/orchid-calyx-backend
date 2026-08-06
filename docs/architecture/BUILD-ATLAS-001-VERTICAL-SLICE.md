# BUILD-ATLAS-001 — Planetary Intelligence Vertical Slice

## Status

Implemented on `feature/atlas-earth-systems-program` for draft PR #420. Not merged or deployed.

## Scope

This build adds the first executable, independently testable Atlas foundation:

- governed spatial dataset contracts;
- biodiversity, Earth-science, conservation, and sampling-effort layer contracts;
- deterministic thematic-map request and manifest assembly;
- map-artifact provenance contracts;
- Atlas reasoning responses that separate observation, inference, uncertainty, and unavailable data;
- Brain registration records for architecture, decisions, and reproducibility;
- fixture-backed end-to-end demonstration and fail-closed tests.

## Implemented files

- `app/atlas_intelligence/models.py`
- `app/atlas_intelligence/assembler.py`
- `app/atlas_intelligence/fixtures.py`
- `app/atlas_intelligence/__init__.py`
- `tests/test_atlas_planetary_intelligence.py`

## Fixture slice

The fixture combines:

1. one resolved orchid taxon occurrence dataset and distribution layer;
2. one elevation Earth-science dataset and raster layer;
3. one protected-area dataset and conservation layer;
4. one sampling-effort dataset and hexagonal density layer.

It produces a canonical thematic-map manifest, an explainable reasoning response, and searchable Brain registration records.

## Governance and validation

The implementation fails closed for invalid CRS values, invalid extents, missing license or attribution, unresolved biodiversity taxon identity, missing datasets, broken layer references, missing temporal coverage for time-dependent layers, duplicate identifiers, unsupported causal language, and unsupported inferences.

Manifest checksums are assembled from canonical sorted JSON so repeated assembly with identical inputs is deterministic.

## Brain capture

The vertical slice creates durable records for:

- Atlas Planetary Intelligence architecture;
- ADR-ATLAS-001;
- each map reproducibility manifest.

Records include durable IDs, aliases, lifecycle state, related objects, source URIs, and content checksums.

## Verification

A focused pytest module is included. GitHub had not yet reported CI checks for the latest commit when this document was written, so passing CI is not claimed here.

## Boundaries

This build does not import production geospatial data, render real map files, publish layers, mutate the production Knowledge Graph, deploy services, merge the PR, or approve scientific conclusions.

## Next slice

The next bounded implementation should add:

- publication-state transition validation;
- concrete map artifact serialization;
- a protected read API for manifests and reasoning responses;
- repository-native autonomous Atlas Director registration;
- Mission Control status payloads;
- an actual render adapter behind the deterministic manifest contract.
