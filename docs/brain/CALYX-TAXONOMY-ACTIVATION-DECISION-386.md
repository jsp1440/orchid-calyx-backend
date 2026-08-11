# CALYX-386 — Read-only taxonomy activation decision packet

Date: 2026-08-08
Parent: #384
Issue: #386

## Purpose

Complete the engineering surface immediately before the explicit owner-governed taxonomy activation boundary without activating anything.

The packet answers one question from durable PostgreSQL evidence: **is the selected Hassler release sufficiently staged and reviewed to be presented to the owner for an activation decision?**

It is not an activation endpoint and never returns activation authority.

## Inputs

The packet reads the durable `taxonomy_pipeline` evidence introduced by migration 107 / PR #619 and the review-provenance ledger introduced by migration 109:

- immutable release identity and source SHA-256;
- exact source row count;
- durable staging checkpoint;
- staged row count;
- release-to-release change report and baseline identity;
- taxonomy review queue;
- durable scientific-review provenance bound to the current review evidence and disposition.

The existing real August 2026 source contract remains:

- `WorldOrchids 26-08 (Aug 2 2026).csv`;
- 34,724 data rows;
- SHA-256 `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`.

The grounded May→August comparison remains review evidence, not an activation instruction.

## Decision states

`HOLD` is returned when any of the following is true:

- staging is incomplete or staged row count does not equal the release row count;
- the durable change report is absent;
- one or more taxonomy review items remain open;
- review items are marked `resolved` or `dismissed` but valid durable provenance is unavailable, malformed, stale, or does not match the current review evidence/disposition.

`READY_FOR_OWNER_ACTIVATION_DECISION` is advisory only and can occur only when those blockers are absent.

Even in that state the packet permanently returns:

- `owner_approval_required=true`;
- `activation_authorized=false`;
- `activation_invoked=false`;
- `automatic_promotion=false`;
- `production_taxonomy_mutation_authorized=false`;
- `knowledge_graph_mutation_authorized=false`;
- `scientific_publication_authorized=false`;
- `read_only=true`.

## Governance defect discovered during implementation

Migration 107's `taxonomy_pipeline.review_queue` contains review key/category/summary/evidence/status timestamps, but it does **not** contain durable reviewer identity, rationale, decision timestamp, or a decision/evidence hash.

Therefore `status='resolved'` or `status='dismissed'` is not sufficient evidence of scientific review. A raw status update could otherwise be mistaken for governed review.

Migration 109 adds `taxonomy_pipeline.taxonomy_review_provenance`. The database rejects empty reviewer identity/rationale and requires a lowercase 64-character SHA-256 digest. Runtime gating goes further: it recomputes the canonical digest from the current release ID, review key, category, summary, evidence, disposition, and review-item update timestamp, and requires `resolved_at >= review_queue.updated_at`. A stale or fabricated provenance row therefore remains blocked.

The decision packet emits blocker:

`REVIEW_DISPOSITION_PROVENANCE_UNAVAILABLE`

whenever a resolved/dismissed item lacks provenance that satisfies that full contract.

This is intentionally stricter than simply checking `open_review_count == 0`.

BUILD-BRAIN-112 was inspected before creating this rule. Its current-main review registry is an in-memory generic review/eligibility structure, not a demonstrated durable taxonomy-review ledger, so it is not silently substituted for taxonomy review provenance.

## Mission Control

Owner-authenticated read-only endpoint:

`GET /api/mission-control/taxonomy/releases/{release_id}/activation-decision`

It derives all evidence server-side and does not expose a mutation method.

## Validation contract

`tests/test_world_plants_activation_decision.py` covers:

- completed staging plus an open duplicate-identity review → `HOLD`;
- status-only `resolved` review → `HOLD` with review-provenance blocker;
- canonical review digest changes when evidence or disposition changes;
- provenance-bound resolved review → advisory owner-decision readiness only;
- completed staging/report with no review items → advisory owner-decision readiness only;
- incomplete staging plus missing report → fail-closed HOLD;
- owner-gated API projection remains read-only and non-authoritative.

Dedicated workflow:

`.github/workflows/calyx-taxonomy-activation-decision-386.yml`

It runs compile, focused tests, Ruff, migration guards, and permanent non-authority assertions. It has `contents: read` permission only.

### Executable validation recovery — 2026-08-08/09

The private-repository hosted-runner incident in #481 was resolved, allowing this slice to receive real executable validation. The first executable attempt exposed only CI-environment defects rather than implementation defects: `pytest` and Ruff were not installed by the focused workflow, then FastAPI's `TestClient` required `httpx`, and invoking the standalone `pytest` entry point did not place the repository root on Python's module path. The workflow was corrected to install `pytest httpx ruff` and to execute focused tests through `python -m pytest`.

Exact implementation/CI head `57a96747c73914e7235b218b686c1351ef192c7a` then passed all applicable PR-triggered validation at that historical checkpoint. Subsequent provenance-hardening commits require their own exact-head validation before merge.

## Current governance boundary

Migration 109 now provides the durable taxonomy-review provenance ledger, but it is additive and does not itself authorize or execute taxonomy activation. The owner-controlled production step remains separate: apply migration 109, record evidence-bound provenance for any resolved/dismissed review items, and inspect the read-only activation-decision packet.

For the real August release, the known duplicate/malformed review evidence means the activation decision must remain `HOLD` until those reviews are represented with valid durable scientific-review provenance.

No production upload, migration execution, staging write, taxonomy activation, canonical relink, Knowledge Graph mutation, publication, deployment, or Azure action is performed by this slice.

Issue #386 remains bounded by explicit owner authority: merge makes the advisory decision machinery canonical, but production migration and any later taxonomy activation remain separate owner-controlled actions.
