# Calyx Brain Record — Atlas Planetary Intelligence

Date: 2026-08-07
Original PR: #420
Current-main release PR: #567
Branch: `feature/atlas-earth-systems-current-main-release`

## Purpose

Record the governed implementation and release recovery of the Orchid Continuum Atlas planetary-intelligence foundation: Earth Systems, deterministic thematic cartography, provenance-aware spatial contracts, read-only APIs, and searchable reproducibility records.

## Implemented capability

The Atlas slice provides strict spatial dataset and layer contracts; CRS, extent, temporal coverage, source lineage, licensing, attribution, and checksum validation; biodiversity, Earth-science, conservation, and sampling-effort layers; deterministic thematic-map manifest assembly; map artifact lineage; reasoning outputs separated into observation, inference, uncertainty, and unavailable information; rejection of unsupported causal language; serializable Brain records; an idempotent registry with conflict and orphan-reference rejection; and read-only Atlas status, dataset, layer, and map APIs.

The fixture-backed vertical slice combines orchid occurrence data, elevation, protected areas, and sampling effort into a deterministic research map manifest and explainable reasoning response. Publication remains disabled inside this module.

## Original validation recovery

The original #420 branch initially had cancelled runner attempts. Once hosted runners resumed, validation exposed and corrected two issues:

1. Ruff import formatting in `app/atlas_intelligence/fixtures.py`.
2. Missing repository-root `PYTHONPATH` in the focused workflow.

Atlas Planetary Intelligence Validation run `31216798996` then completed successfully on the validated implementation, passing checkout, Python setup, dependency installation, compilation, Ruff, the full focused Atlas pytest suite, and cleanup.

## Current-main release recovery

By the time release authority was granted, original PR #420 had drifted far behind active `main` and GitHub reported it non-mergeable. Comparison against current `main` showed the Atlas paths remained additive rather than conflicting with newly released operator/governance work. The validated Atlas files were therefore rebuilt on a fresh branch from current `main` rather than forcing the stale branch.

Replacement PR #567 preserves the tested contracts and CI corrections while updating the build record to the current release context.

Fresh Atlas Planetary Intelligence Validation run `31219396372` completed successfully on implementation head `1a3c98a3050d313bd76558d6facf1c66121cfa7e`:

- runner setup: pass;
- repository checkout: pass;
- Python setup: pass;
- focused dependency installation: pass;
- Atlas package compilation: pass;
- Ruff validation: pass;
- complete focused Atlas pytest suite: pass;
- cleanup: pass.

This documentation-only commit records the exact current-main release evidence and does not alter Atlas runtime behavior.

## Governance boundaries

This Atlas foundation is read-only/candidate infrastructure. It does not itself authorize or perform:

- production Atlas-layer publication;
- write APIs;
- automatic scientific approval;
- production Knowledge Graph mutation;
- taxonomy activation;
- production geospatial ingestion.

Those operations require their own concrete governed artifacts and execution paths. Release of this foundation does not manufacture scientific evidence or a production mutation target.
