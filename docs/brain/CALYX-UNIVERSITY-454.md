# CALYX-454 — Orchid Continuum University foundation

Status: IMPLEMENTED / REVIEW-ONLY

## Delivered

- Owner-scoped course and lesson contracts with prerequisites, measurable objectives, concept coverage, activities, accessible learner payloads, and instructor payloads.
- Evidence-linked lesson content bound to Knowledge Explorer candidate concepts and exact evidence IDs.
- Glossary resolution through Knowledge Explorer multilevel definitions, preserving candidate-only and scientific-review-required state.
- Virtual-lab scenarios bound to a private Research Station reproducibility manifest.
- Deterministic lab state machine: not_started → observe → hypothesize → simulate → reflect → complete, with bounded backwards transitions for inquiry refinement.
- Explicit rejection of real actuator/equipment actions.
- Versioned question banks with answer rationales, objective references, and rubrics.
- Progress-event records that do not make credential decisions.
- Separate accessible learner and instructor lesson payloads.
- Protected Mission Control routes and readiness surface.
- Deterministic focused tests plus dependency regression coverage.

## Governance boundaries

The University slice is educational infrastructure only. It does not authorize autonomous grading of high-stakes credentials, scientific publication, real laboratory/equipment control, production deployment, merge, taxonomy activation, or production Knowledge Graph mutation. Knowledge Explorer science remains candidate-only and review-required. Research Station content remains private by default.

## Dependency stack

CALYX-454 is intentionally stacked on CALYX-453 Research Station, which itself depends on CALYX-448 Literature Intelligence. The Knowledge Explorer implementation from CALYX-444 is staged into this branch to satisfy glossary/evidence contracts until the dependency chain is merged through governance.

## Validation gate

A dedicated `CALYX University 454` workflow compiles the changed surface, runs University plus Knowledge Explorer and Research Station focused tests, asserts permanent non-authority strings, runs Ruff on the changed University surface, and checks diff hygiene. The PR must remain draft/unmerged until exact-head CI is green and dependency/review gates are satisfied.
