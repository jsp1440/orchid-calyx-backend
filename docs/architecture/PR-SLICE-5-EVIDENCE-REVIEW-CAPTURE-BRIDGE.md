# PR Slice 5 — Evidence, Review, and Brain Capture Bridge

## Purpose

Connect completed Canonical Brain execution receipts to the existing Calyx evidence-governance stack instead of creating parallel artifact, review, or Brain-capture implementations.

## Existing authoritative components reused

- `app/calyx_orchestrator/artifact_registry.py` — immutable artifact identity, checksum, provenance, evidence URIs, lineage, and duplicate-content detection.
- `app/calyx_orchestrator/review_eligibility.py` — required review classes, self-approval prohibition, immutable decisions, and release eligibility.
- `app/calyx_orchestrator/brain_capture.py` — reviewed, evidence-backed, candidate-only Brain capture bundles.

## New translation boundary

`app/canonical_brain/evidence_bridge.py` converts one completed Canonical Brain `ExecutionReceipt` into:

1. an `ArtifactRegistration` containing the canonical receipt as deterministic JSON;
2. a `ReviewRequest` tied to explicit required review classes; and
3. a `BrainCaptureBundle` containing a validation candidate sourced from that artifact.

## Invariants

- only completed receipts are eligible;
- at least one evidence URI is required;
- a 64-character output checksum is required;
- review requester and producer must be distinct;
- duplicate review classes are rejected;
- all generated objects are deterministic;
- artifact metadata and Brain payloads remain candidate-only and unpublished;
- this bridge performs no registration, approval, capture, publication, deployment, or production mutation itself;
- the existing Calyx review and capture registries remain authoritative for subsequent state changes.

## Validation

Focused tests demonstrate deterministic translation, rejection of incomplete receipts, self-review protection, duplicate review-class rejection, and end-to-end use of the existing artifact, review, and Brain-capture gates.
