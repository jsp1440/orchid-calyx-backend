# Calyx Brain current operational status — August 2026

This document supersedes older capability inventories where later merged builds changed the operational state.

## Operational core

- Knowledge Graph queries and deterministic inference: implemented.
- Reasoning Ledger and governed inference submission: implemented.
- Controlled publication adapter and scientific approval boundary: implemented.
- External language-model synthesis: implemented as synthesis-only; server policy remains authoritative.
- Durable journalism evidence/article persistence: implemented.
- Durable Calyx orchestrator and preproduction worker queue: implemented; activation remains environment-gated.
- Mission Control orchestrator status: implemented.

## Education and website design

### Design Intelligence

The existing Design Intelligence corpus and semantic reasoning service are now exposed through the canonical Brain boundary and Calyx tool registry. Calyx can perform read-only readiness inspection and provenance-aware design searches covering UX, UI, accessibility, information architecture, design systems, educational psychology, learning sciences, and scientific visualization.

Canonical Brain routes:

- `GET /brain/education-design/readiness`
- `POST /brain/education-design/search`

Calyx tools:

- `design_intelligence.readiness`
- `design_intelligence.search`
- `education.readiness`

### Education

Educational-design classification is operational through the existing Design Intelligence knowledge layer, including Bloom, Mayer multimedia learning, cognitive-load theory, Universal Design for Learning, active learning, and inquiry learning.

The complete Orchid Continuum University runtime is still incomplete. Course persistence, curriculum sequencing, assessments, student progress, and virtual-laboratory execution remain explicit gaps. Calyx may inspect these gaps and prepare bounded recommendations, but it cannot publish courses or mutate the website automatically.

## Orchestrator coverage

The overnight profile now includes read-only jobs for:

- website design, accessibility, navigation, information architecture, and scientific visualization;
- University curriculum, lessons, assessments, student progress, and virtual-laboratory readiness.

## Governance

- Read-only inspection and recommendation preparation may run automatically in an activated preproduction worker.
- Repository changes, frontend implementation, deployment, course publication, and schedule activation require owner approval.
- Canonical scientific publication remains behind the separate scientific-review gate.
- No private chain-of-thought is stored.

## Remaining priority work

1. Certify the orchestrator against the preproduction PostgreSQL migration and worker service.
2. Connect actual University course, lesson, assessment, learner-progress, and virtual-lab runtimes.
3. Add approval-driven conversion of design recommendations into GitHub issues and Draft PRs.
4. Add frontend Mission Control panels for education/design findings.
5. Complete end-to-end Brain operational certification.
