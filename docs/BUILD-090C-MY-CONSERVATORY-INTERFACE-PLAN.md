# BUILD-090C — My Conservatory Interface Plan

## Planning process

This demonstration runs the merged BUILD-090B planning service from an owner-approved Product Request through context capture, BUILD-089 evidence retrieval, reasoning, material-conflict recording, plan drafting, and submission for human review. The result is an immutable planning chain. It is not a frontend, wireframe, component library, implementation authorization, production deployment, or Knowledge Graph publication.

The Product Request is version 1 for the Orchid Continuum product family. It defines collection owners, authorized collaborators, and read-only guests; mobile, tablet, and desktop targets; authenticated writes; private-by-default sharing; scientific integrity; accessibility; provenance; and eighteen explicit goals: personal collection, QR identification, plant passport, photographs, tag history, taxonomy, parentage, bloom, repotting and culture histories, environmental sensors, greenhouse locations, inventory, reminders, awards, provenance, exports, and future graph integration.

The context snapshot references the BUILD-089C corpus, BUILD-090 architecture, Orchid Continuum conventions, BUILD-087 scientific requirements, accessibility obligations, educational and collection-management goals, privacy requirements, and BUILD-082–090 provenance rules. Security/privacy, scientific integrity, accessibility, and provenance remain hard constraints.

## Retrieved evidence

The evidence package issues normalized queries for accessible dashboard navigation/search, mobile progressive disclosure and validation, reduced motion, scientific visualization with uncertainty/provenance, and educational cognitive-load guidance. Retrieval uses the BUILD-089 hybrid reasoning service and retains semantic-unit identifiers, document identifiers, exact source locators, citations, ranking scores and decomposed explanations, corpus/provider versions, related concepts, and rights restrictions.

Coverage is derived from returned classifications and corpus metadata. Accessibility, UX, motion, and available component guidance may be covered or partial. Dashboard design, educational psychology, scientific visualization, and branding remain explicit gaps when the corpus returns no qualifying units. `NOT_PRESENT_IN_SOURCE_CORPUS` is never reported as provider failure, and `RETRIEVAL_UNAVAILABLE` is never treated as proof of a corpus gap. No guidance is fabricated.

All evidence remains `USER_SUPPLIED_INTERNAL_RESEARCH_ONLY`, with reuse license `NOT_SUPPLIED` and public redistribution prohibited. Only bounded internal excerpts are retained.

## Reasoning summary

Ten concise, auditable reasoning records address:

1. Task-oriented navigation across collection, activity, reports, and settings.
2. A stable My Plants inventory for filtering, review, and plant access.
3. Scientific-name-aware collection search with explicit filters.
4. QR resolution to a plant passport with unknown and duplicate states.
5. A provenance-visible plant passport separating identity, observations, histories, media, and care.
6. Task-specific append-only editing for repotting, bloom, culture, tag, and media history.
7. Environmental readings with location, time range, units, gaps, device provenance, and no automatic culture conclusion.
8. Plant-linked reminders with due windows, completion history, and accessible alerts.
9. Semantic structure, keyboard operation, visible focus, reduced motion, and text alternatives.
10. Accepted names, synonyms, parentage, uncertainty, sources, and observation-versus-interpretation distinctions.

Each record retains alternatives, assumptions, unresolved questions, risks, supporting evidence references, confidence factors, corpus gaps, and implementation implications. It stores no hidden chain of thought.

## Material conflicts

Five material conflicts remain open and require explicit role-aware decisions:

- Simplicity versus scientific completeness — scientific reviewer.
- Mobile field work versus dense desktop management — UX reviewer.
- Rapid entry versus scientific/provenance validation — product owner.
- Sharing versus private locality and ownership data — privacy/security reviewer.
- Novice clarity versus expert taxonomic detail — UX reviewer.

No conflict is silently resolved. Privacy and scientific-integrity conflicts are hard blockers. All retain alternatives, evidence, authority levels, severity, affected users/workflows, recommended resolution, and `DECISION_REQUIRED` status.

## Interface Plan

### Information architecture and navigation

- Dashboard
  - My Plants
  - Reminders
  - Recent Activity
- My Plants
  - Plant Detail
  - Add Plant
  - QR Scanner
- Plant Detail
  - Bloom History
  - Repot Plant
  - Environmental History
  - Media Gallery
- Utilities
  - Search
  - Reports
  - Settings

Primary navigation is Dashboard, My Plants, Scan, Search, Reports, and Settings. Mobile prioritizes the current task, tablet uses adaptive panes, and desktop provides a collection workspace. Offline behavior is limited to authorized read-only cached identity; implementation requires a later explicit decision.

### Screen inventory

Every screen record contains purpose, users, workflows, required data, interactions, accessibility, scientific presentation, recoverable errors, named loading state, explanatory empty state, acceptance criteria, and evidence-package references.

| Screen | Planning purpose | Key requirements |
|---|---|---|
| Dashboard | Collection status and next work | Reminders, recent activity, accessible summaries; no false dashboard guidance claim when corpus coverage is absent |
| My Plants | Searchable/filterable inventory | Scientific identity, location, status, pagination, bulk review |
| Plant Detail | Plant passport | Accepted name, synonyms, parentage, uncertainty, provenance, media and append-only histories |
| QR Scanner | Identify a plant | Permission, unknown/duplicate codes, manual alternative, announced status |
| Add Plant | Create collection identity | Progressive fields, validation, provenance, save recovery, no silent defaults |
| Repot Plant | Append repotting event | Date, medium, container, observations, units, actor and source |
| Bloom History | Review and append bloom events | Dates, counts, measurements, photographs, awards and uncertainty |
| Environmental History | Review sensor context | Device, location, time range, units, missing data, accessible chart alternative |
| Media Gallery | Review licensed plant media | Attribution, image provenance, captions, alternative text, rights status |
| Search | Find plants and histories | Scientific-name-aware query, explicit filters, deterministic ordering, empty/error recovery |
| Reports | Produce owner-authorized summaries/exports | Scope, provenance, rights, private-field exclusion, accessible tables |
| Settings | Manage owner-controlled policy | Roles, sharing, privacy, devices, units, reminders and audit-visible changes |

### Cross-cutting contracts

Accessibility requires semantic headings, keyboard access, visible focus, accessible names/descriptions, screen-reader status, scaling, contrast, non-color meaning, reduced motion, adequate targets, accessible errors/forms/tables, chart alternatives, cognitive support, plain language, and responsive accessibility.

Scientific presentation preserves names and authorship, accepted names and synonyms, uncertainty, evidence/provenance classes, conflicting assertions, observation versus interpretation, spatial and temporal scope, units/method context, specimen/occurrence context, conservation sensitivity, protected locality, licenses, image provenance, citations, and future graph relationships without publishing them.

Privacy and security require private-by-default collections, protected locality, role-aware sharing, authenticated writes, immutable audit history, and no unrestricted corpus content. History is appended rather than overwritten.

## Persistence, lifecycle, and review

The demonstration persists one Product Request, one context snapshot, one evidence package, ten reasoning records, five material conflicts, Interface Plan version 1 in `PLAN_DRAFTED`, and Interface Plan version 2 in `REVIEW_REQUIRED`. Version 2 supersedes version 1 without mutation. Product owner, UX, accessibility, scientific, privacy/security, and technical-feasibility reviews are required. No approval is fabricated.

Deterministic replay resolves to the same artifact identities and emits no duplicate audit events. PostgreSQL reconstruction verifies Product Request and Interface Plan versions and append-only history.

## Limitations

- The BUILD-089 corpus has known gaps; absence is reported, not replaced with invented guidance.
- No owner or domain reviewer decisions are recorded by this demonstration.
- Sensor protocol, sharing granularity, offline behavior, and export policy require later decisions.
- The plan is implementation-neutral and contains no React, HTML, CSS, components, pages, deployment, graph publication, or implementation authorization.
- Production-scale latency and usability have not been measured.

## BUILD-091 implementation recommendations

BUILD-091 should begin only after required reviewers resolve the five conflicts and approve the identical plan hash. It should define a controlled implementation handoff, frontend repository authority, component/design-token contracts, API validation, threat model, accessibility test matrix, scientific-content acceptance tests, observability, rollback, and release approval. It must not infer implementation authority from this planning artifact.

**READY FOR BUILD-091 PLANNING HANDOFF AFTER HUMAN REVIEW**
