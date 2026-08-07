# PR #558 — Canonical Brain Codex Review Remediation

## Purpose

Record the five actionable review findings raised against superseded PR #525, the current-main remediation applied in PR #558, and the validation evidence required before the replacement can be considered review-ready.

## Replacement lineage

PR #525 accumulated validated Canonical Brain functionality but became stale while `main` advanced substantially. Rather than force-rewrite its history, the remediated surface was replayed onto `stabilize/canonical-brain-current-main-remediated`, created from current `main`. The one shared deployed file, `app/brain/routes.py`, was explicitly reconciled to the current runtime before replaying the Canonical additions.

Branch-maintenance PR #557 replayed the remediated surface into that current-main branch. It did not merge Canonical Brain to production `main`.

## Review findings and remediations

### 1. P1 — Canonical routes were not deployed

**Finding:** `create_brain_router()` existed and tests mounted it into a synthetic FastAPI app, but the real application did not mount `/brain/canonical/*`.

**Remediation:** `create_brain_router()` now accepts a configurable prefix and the existing authenticated `/brain` router mounts it at `/canonical`. Therefore the deployed route table contains `/brain/canonical/status`, `/brain/canonical/search`, and `/brain/canonical/admission/evaluate`, inheriting the existing Brain authentication and Mission Control CORS dependencies.

The portable validator now compiles, lints, fingerprints, and tests `app/brain/routes.py` as part of the Canonical validation boundary.

### 2. P1 — Direct Brain capture bypassed review authority

**Finding:** `capture_build_bundle()` could register arbitrary `BrainObject` records, including scientific/design objects or objects already marked `approved`, directly into the canonical registry.

**Remediation:** direct capture is limited to operational metadata object types (`build`, `validation`, `reproducibility`, `risk`) and rejects any object claiming lifecycle `approved`. Scientific/design knowledge must use the existing reviewed candidate-capture pathway and cannot be promoted by the operational handoff.

### 3. P1 — Completion provenance could be forged in process

**Finding:** Canonical `record_completed()` accepted a caller-provided Calyx receipt object. Although the receipt checksum was validated, the object itself was constructible by application code and did not prove that the authoritative executor had actually produced and durably recorded it.

**Remediation:** Canonical completion no longer accepts a receipt object. It requires a SQLAlchemy `Session`, a durable `CalyxProgramJob` identifier, and an executor role key. Completion resolves the persistent program-job row from the database, requires the row to be persistent and terminally delivered, decodes the executor receipt previously stored in `evidence_json` by the existing `LeaseExecutionBridge`, verifies executor allowlisting, role binding, checksums, output, and evidence URIs, and requires the durable program-job URI to be present in the evidence set. Only then can the Canonical queue transition to `completed`.

Focused tests use an in-memory SQLAlchemy database, a real durable program/job row, the existing allowlisted autonomy probe executor, and the existing `LeaseExecutionBridge` to prove the completion path end to end.

### 4. P2 — Lease attempts were caller controlled

**Finding:** callers could supply the retry attempt number when acquiring a lease, allowing attempt counters to be reset or advanced outside manager policy.

**Remediation:** `ExecutionLeaseManager.acquire()` derives attempts internally. A live same-worker retry is idempotent; a different worker cannot steal a live lease; an expired lease increments the prior attempt exactly once; released/cancelled leases cannot be reacquired; and acquisition fails after `max_attempts`. Recovery changes to `manual_review` once the ceiling is reached.

### 5. P2 — Deterministic assignment was not idempotent after scheduling

**Finding:** `assign()` checked queue status before checking whether the build already had an assignment, so retrying an already scheduled build raised instead of returning the existing deterministic assignment.

**Remediation:** existing assignment lookup now precedes queue-state validation. Repeated assignment requests for the same build return the original assignment without a second queue transition.

## Authoritative validation

PR #558 head after the validation dependency correction: `15170ada648f40f52d1f1ff41413e3f71881a54f`.

Canonical Brain Validation run #120 / Actions run `31212873974` executed against GitHub's PR merge ref on current `main` and passed:

- compile: **passed**;
- Ruff: **passed**;
- pytest: **56 passed**;
- deployed `app/brain/routes.py`: included in compile/lint/fingerprint boundary;
- receipt schema: `1.2`;
- content-bound `validated_tree_sha256`: `a27d4964e3551967f4781e45b38d8a783929220d95c4cb84f60bd093bcf1b960`.

The first current-main run (#119) also proved compile and Ruff clean, but pytest collection was blocked because the workflow omitted `httpx`, required by FastAPI/Starlette TestClient. The workflow was corrected to install `httpx`; no application-code workaround was used.

At the same validated head, BUILD-088E and the CALYX Agent, Journalism, Education Design, and Core Rebase validation workflows reported success. Full Calyx Brain Integration Validation and End-to-End Certification were still running when this record was first written; their final state must be checked before PR #558 is promoted from draft.

## Safety and authority

This remediation grants no authority to merge to `main`, deploy, publish, access credentials, execute arbitrary external mutations, activate taxonomy, mutate production databases, or mutate the production Knowledge Graph. Branch-maintenance replay was performed only to obtain a current-main validation surface.
