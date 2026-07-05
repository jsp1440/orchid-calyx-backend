# BUILD-031 — Institutional Memory and Founding Charter

## Objective

Preserve the founding philosophy of the Orchid Continuum as first-class institutional memory in GitHub and prepare it for Brain storage through the `oc_philosophy` schema.

## Why this build matters

The Orchid Continuum is not only a technical platform. It is an integrative knowledge system whose purpose is to cultivate understanding by revealing relationships. BUILD-031 makes that purpose durable and version-controlled so future contributors and Calyx itself can inherit the project identity, not only its code.

## Deliverables

### Version-controlled philosophy documents

Added:

- `brain/philosophy/FOUNDING_CHARTER.md`
- `brain/philosophy/CONSTITUTION.md`
- `brain/philosophy/INTEGRATIVE_SCIENCE.md`
- `brain/philosophy/FOUNDING_DIALOGUE_I.md`
- `brain/philosophy/DESIGN_PRINCIPLES.md`

### Brain schema migration

Added:

- `migrations/BUILD-031-oc-philosophy.sql`

This migration creates:

- `oc_philosophy.documents`
- `oc_philosophy.principles`
- `oc_philosophy.constitution_articles`
- `oc_philosophy.institutional_memory`

## Foundational principle

> The Orchid Continuum exists to cultivate understanding by revealing relationships.

## North Star

Every future decision should be evaluated by one question:

> Does this help someone discover a meaningful relationship they could not see before?

## Future implementation notes

A later build should load these documents into Calyx startup context and expose them through a read-only philosophy endpoint, such as:

- `GET /api/philosophy/charter`
- `GET /api/philosophy/constitution`
- `GET /api/philosophy/principles`

A later build should also seed the `oc_philosophy` tables from the Markdown files and add constitutional compliance checks to the Runtime Planner.

## Status

BUILD-031 establishes the permanent repository home and schema foundation for the Orchid Continuum founding philosophy.
