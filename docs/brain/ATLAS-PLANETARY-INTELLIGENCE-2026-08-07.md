# Calyx Brain Record — Atlas Planetary Intelligence

Date: 2026-08-07
Authoritative PR: #420
Branch: `feature/atlas-earth-systems-program`

## Purpose

Record the validated implementation state of the Orchid Continuum Atlas planetary-intelligence foundation, including Earth Systems, deterministic thematic cartography, provenance-aware spatial contracts, read-only APIs, and the CI recovery work completed after hosted-runner execution resumed.

## Implemented capability

The Atlas slice provides strict spatial dataset and layer contracts; CRS, extent, temporal coverage, source lineage, licensing, attribution, and checksum validation; biodiversity, Earth-science, conservation, and sampling-effort layers; deterministic thematic-map manifest assembly; map artifact lineage; reasoning outputs separated into observation, inference, uncertainty, and unavailable information; rejection of unsupported causal language; serializable Brain records; an idempotent in-memory registry with conflict and orphan-reference rejection; and protected read-only Atlas status, dataset, layer, and map APIs.

The fixture-backed vertical slice combines orchid occurrence data, elevation, protected areas, and sampling effort into a deterministic research map manifest and explainable reasoning response. Publication remains disabled.

## CI recovery and corrective work

Earlier Atlas workflow attempts had been cancelled before execution. Once GitHub-hosted runners resumed, executable validation exposed two concrete issues:

1. `app/atlas_intelligence/fixtures.py` had a Ruff import-formatting failure. The imports were normalized without changing runtime semantics.
2. The focused workflow did not set the repository root on `PYTHONPATH`, causing `ModuleNotFoundError: No module named 'app'` during pytest collection despite compile and Ruff passing. The workflow now sets `PYTHONPATH: .` at the job level.

After both corrections, Atlas Planetary Intelligence Validation run `31216798996` completed successfully. Checkout, Python setup, focused dependency installation, package compilation, Ruff validation, the full focused Atlas pytest suite, and cleanup all passed.

Validated branch commits:
- `dc238dc632d69f5000bcb7971fdb770a2da7562e` — Ruff import formatting repair.
- `eaa3bd55e433f4a8a445e24bf98e50abda1ed268` — focused CI import-path repair and green validation head.

## Governance boundaries

This validation does not grant production publication or deployment authority. The following remain explicitly disabled or outside this slice:

- production Atlas layer publication;
- write APIs;
- automatic scientific approval;
- production Knowledge Graph mutation;
- taxonomy activation;
- deployment authority;
- automatic merge.

Atlas remains a governed, read-only planetary-intelligence foundation pending explicit release decisions and production data-source integrations.
