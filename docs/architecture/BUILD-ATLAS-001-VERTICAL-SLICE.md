# BUILD-ATLAS-001 — Planetary Intelligence Vertical Slice

## Status

Rebuilt on `feature/atlas-earth-systems-current-main-release` from current `main` after the original PR #420 drifted behind the active backend branch. Release validation is required on the exact rebuilt head before merge.

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
- `app/atlas_intelligence/registry.py`
- `app/atlas_intelligence/api.py`
- `app/atlas_intelligence/__init__.py`
- `tests/test_atlas_planetary_intelligence.py`
- `tests/test_atlas_registry_api.py`

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

The API and registry are read-only/candidate surfaces. No Atlas publication, deployment, taxonomy activation, or production Knowledge Graph mutation is performed by this slice.

## Brain capture

The vertical slice creates durable records for:

- Atlas Planetary Intelligence architecture;
- ADR-ATLAS-001;
- each map reproducibility manifest.

Records include durable IDs, aliases, lifecycle state, related objects, source URIs, and content checksums.

## Verification history

The original implementation received a real hosted-runner green gate in Atlas Planetary Intelligence Validation run `31216798996` after fixing Ruff import formatting and setting `PYTHONPATH: .`. The current-main replacement preserves those validated runtime/test files and must receive a fresh executable run before release.

## Boundaries

This build does not import production geospatial data, render real map files, publish production layers, mutate the production Knowledge Graph, or self-approve scientific conclusions.

## Next slice

The next bounded implementation should add:

- publication-state transition validation;
- concrete map artifact serialization;
- protected integration with authoritative application routing;
- Mission Control status payloads;
- an actual render adapter behind the deterministic manifest contract;
- real source adapters only after provenance, licensing, and persistence requirements are satisfied.
