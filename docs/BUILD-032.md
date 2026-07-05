# BUILD-032 — Calyx Frontend Workbench

## Objective

Turn Calyx's frontend inspection work into an organized, philosophy-aware frontend repair workbench.

BUILD-028 proved that Calyx can inspect the Orchid Continuum frontend. BUILD-031 preserved the founding philosophy. BUILD-032 connects those two threads by creating a deterministic queue of frontend repair work organized around the Living Continuum vision.

## What this build adds

- `runtime/frontend_workbench.py`
- `FrontendWorkbench.queue_from_audit()`
- Deterministic frontend repair queue
- Philosophy alignment metadata for each repair task

## Current mode

Planning only. No GitHub writes, no branch creation, no direct file edits.

## Repair priorities

1. Restore Genus of the Day image experience.
2. Make Discovery Trails visible and connected.
3. Unify the homepage narrative into one canonical flow.
4. Audit backend and image URL configuration.
5. Connect homepage modules to the Knowledge Layers model.

## Philosophy alignment

Each task includes alignment to BUILD-031 principles such as:

- Beauty
- Relationships
- Stewardship
- Ways of Learning
- Integrative Science
- Provenance
- Living Graph
- Knowledge Layers
- Ways of Thinking

## Next build

A later build should wire this workbench into one of the following:

- a GitHub connector task such as `frontend_workbench`, or
- a runtime endpoint such as `GET /api/runner/frontend-workbench`.

After that, Calyx can use the queue to generate reviewable frontend patch plans and PRs.
