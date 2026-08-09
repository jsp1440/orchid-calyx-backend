# CALYX-386 — Read-only taxonomy activation decision packet

Date: 2026-08-08
Parent: #384
Issue: #386

## Purpose

Complete the engineering surface immediately before the explicit owner-governed taxonomy activation boundary without activating anything.

The packet answers one question from durable PostgreSQL evidence: **is the selected Hassler release sufficiently staged and reviewed to be presented to the owner for an activation decision?**

It is not an activation endpoint and never returns activation authority.

## Inputs

The packet reads only the merged `taxonomy_pipeline` evidence introduced by migration 107 / PR #619:

- immutable release identity and source SHA-256;
- exact source row count;
- durable staging checkpoint;
- staged row count;
- release-to-release change report and baseline identity;
- taxonomy review queue.

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
- review items are marked `resolved` or `dismissed` but durable reviewer/rationale provenance is unavailable.

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

The decision packet explicitly refuses that inference and emits blocker:

`REVIEW_DISPOSITION_PROVENANCE_UNAVAILABLE`

This is intentionally stricter than simply checking `open_review_count == 0`.

BUILD-BRAIN-112 was inspected before creating this rule. Its current-main review registry is an in-memory generic review/eligibility structure, not a demonstrated durable taxonomy-review ledger, so it is not silently substituted for missing taxonomy review provenance.

## Mission Control

Owner-authenticated read-only endpoint:

`GET /api/mission-control/taxonomy/releases/{release_id}/activation-decision`

It derives all evidence server-side and does not expose a mutation method.

## Validation contract

`tests/test_world_plants_activation_decision.py` covers:

- completed staging plus an open duplicate-identity review → `HOLD`;
- status-only `resolved` review → `HOLD` with review-provenance blocker;
- completed staging/report with no review items → advisory owner-decision readiness only;
- incomplete staging plus missing report → fail-closed HOLD;
- owner-gated API projection remains read-only and non-authoritative.

Dedicated workflow:

`.github/workflows/calyx-taxonomy-activation-decision-386.yml`

It runs compile, focused tests, Ruff, and permanent non-authority assertions. It has `contents: read` permission only.

## Current governance boundary

This slice does not create the missing durable taxonomy-review disposition ledger because doing so is a separate schema/review-workflow design decision and must not be hidden inside an activation-readiness view.

For the real August release, the known duplicate/malformed review evidence means the activation decision must remain `HOLD` until review is represented with durable scientific-review provenance.

No production upload, migration, staging write, taxonomy activation, canonical relink, Knowledge Graph mutation, publication, deployment, or Azure action is performed by this slice.

Issue #386 requires the agent to stop before merge. Keep the implementation draft/unmerged until executable exact-head validation succeeds and the remaining review-provenance/governance requirements are resolved.
