# BUILD-091 — My Conservatory Implementation Specification

BUILD-091 is an artifact-only bridge between the approved BUILD-090C Interface Plan and future frontend construction. It references every immutable BUILD-090 source artifact by identity, version, and integrity hash and never regenerates or approves planning decisions.

## Architecture and lifecycle

The service deterministically produces versioned, append-only, reviewable specification sets. In-memory and PostgreSQL repositories share one contract. The additive `implementation_planning` schema stores immutable specification sets, typed child artifacts, reviews, and audit events; triggers reject updates and deletes. Authenticated internal routes expose generation, retrieval, history, review, audit, and health. No frontend generation, implementation authorization, public access, or Knowledge Graph publication exists.

## Catalogs

The page catalog covers Dashboard, My Plants, Plant Detail, Add Plant, QR Scanner, Repot Plant, Bloom History, Environmental History, Gallery, Reports, Search, and Settings. Every page defines purpose, permissions, route, layout, sections, widgets, reusable components, backend contracts, loading and empty states, validation, errors, accessibility, keyboard and responsive behavior, transitions, telemetry, acceptance criteria, provenance, and readiness.

The component catalog contains 39 reusable specifications including Orchid Card, Plant Header, QR Badge, Photo Gallery, Trait Table, Parentage Tree, Timeline, Environmental Graph, Location Badge, Reminder Panel, Tag History, Citation Panel, Provenance Viewer, Scientific Name Display, Collection Table, Search Result Card, and Filter Panel. Each defines inputs, outputs, props, events, accessibility, state, dependencies, reuse, and readiness.

The navigation artifact covers the complete graph, deep links, breadcrumbs, search and QR routing, and mobile and desktop navigation. Seventeen state domains define ownership, optimistic behavior, synchronization, caching, offline boundaries, rollback, and conflict resolution.

## Backend integration

The API catalog reuses the verified existing orchid verification and award endpoints and marks their incomplete screen coverage PARTIAL. Fifteen non-duplicative product endpoints are proposed for collection, plant, QR, repot, bloom, environmental, media, reports, search, and settings behavior. Twenty-four request/response contracts define required data. Every mapping records authentication, authorization, pagination, filtering, ordering, validation, errors, consumers, provenance, status, and its exact dependency. This build does not implement those endpoints.

Accessibility, scientific-name and provenance integrity, privacy, and telemetry are cross-cutting contracts. Original scientific evidence and provenance remain immutable.

## Navigation graph and sequencing

Authenticated entry routes to Dashboard, with primary navigation to My Plants, Search, Reports, and Settings. Collection and search results deep-link to Plant Detail; QR scans resolve only after validation. Plant Detail links to repot, bloom, environmental, gallery, provenance, and parentage contexts.

The dependency sequence is: contract validation, Foundation, Navigation, Collection Management, Plant Detail, Environmental History, Reports, Accessibility Review, and Integration Testing. Each phase has explicit prerequisites, deliverables, readiness, and blockers.

## Review and readiness

All five BUILD-090C `DECISION_REQUIRED` conflicts remain unresolved and are mapped to affected pages, components, APIs, sequence, and readiness. The source Interface Plan stays `REVIEW_REQUIRED`. Specification generation, provenance, navigation, state, versioning, review, audit, and persistence are READY. Screen construction is PARTIAL where product endpoints are proposed but absent. Implementation authorization is BLOCKED until the five conflicts are resolved and the Interface Plan receives the required approval.

BUILD-092 may consume these specifications only for work whose dependencies are satisfied. The existence of a BUILD-091 artifact is not implementation approval.

## Validation and limitations

Tests cover deterministic generation, idempotency, catalogs, provenance, versioning, lifecycle, role-aware review, audit history, API reuse and non-duplication, PostgreSQL 16 migration repeatability and immutability, authentication, and prohibited frontend output. BUILD-089 and BUILD-090 regressions run in CI.

Intentional exclusions are frontend artifacts, product endpoints, implementation authorization, production deployment, reviewer UI, and Knowledge Graph publication. The five BUILD-090C material conflicts require human resolution.
