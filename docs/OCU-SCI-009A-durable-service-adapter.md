# OCU-SCI-009A — Durable Session Service Adapter

## Status

Prepared activation code only. No migration is applied and no production environment flag is changed by this build.

## Purpose

Connect the already-reviewed durable repository to the existing University service contract while preserving the production sequencing gate established by OCU-SCI-007 and OCU-SCI-008A.

## Runtime behavior

When the cryptographic durable-session gate is closed, existing session routes continue to use the process-local prototype store exactly as before.

When every durable prerequisite is true, the same authenticated session routes dispatch to the Postgres repository and require optimistic-concurrency revisions for learner mutations.

Capability and release-readiness reporting expose the selected persistence mode explicitly:

- `process_local_memory`
- `postgres_durable`

The current approved read-only release continues to report `process_local_memory`, learner writes disabled, publication disabled, Candidate Knowledge writes disabled, and Calyx model calls disabled.

## Durable learner mutations

Durable event appends require `expected_revision`. A stale value fails with `REVISION_CONFLICT`; no last-write-wins overwrite is permitted.

Backend API-key actors may inspect durable sessions operationally but may not author learner events.

## Submission

A new gated endpoint contract is prepared:

`POST /api/learning/sessions/{session_id}/submit`

Submission requires:

- durable activation gate open;
- authenticated learner ownership;
- exact expected revision;
- inquiry progress through the `communicate` stage.

Submission appends an immutable `session_submitted` event, advances the revision, moves the inquiry to `contribute`, and locks ordinary learner-event editing.

When a qualified reviewer requests changes, the session reopens at `communicate` so the learner can revise and resubmit rather than becoming trapped at `contribute`.

## Human review

A new gated review contract is prepared:

`POST /api/learning/sessions/{session_id}/reviews`

The review route uses the canonical Mission Control governed `AccessPrincipal` and capability system. Generic administrator status or possession of the shared backend API key is **not** sufficient scientific-review authority.

Review decisions require an active scientific-review qualification plus the capability appropriate to the decision:

- `changes_requested` → `review.science`
- `approved_for_learning` → `review.science`
- `approved_for_candidate_knowledge_consideration` → `review.expert`

Accepted scientific-review qualifications are bounded to the governed reviewer qualifications already recognized by Mission Control. The service performs this check itself in addition to route authentication, so a route-level mistake cannot silently bypass reviewer governance.

Each persisted review records authorization provenance:

- reviewer principal ID;
- required reviewer capability;
- reviewer roles;
- active scientific-review qualifications;
- exact reviewed learner revision.

The Candidate Knowledge consideration decision means only that the reviewed work may later enter the separate Candidate Knowledge governance process. The University transaction cannot promote Candidate Knowledge or publish anything.

## Structural scientific safeguards

OCU-SCI-009A preserves and strengthens the OCU-SCI-008 database constraints:

- publication remains false;
- automatic Candidate Knowledge remains false;
- human review remains required;
- event sequence/revision uniqueness is retained;
- review records cannot claim publication;
- review records cannot claim Candidate Knowledge promotion;
- review records must carry an approved reviewer capability;
- reviewer roles and qualifications are retained as JSON provenance arrays.

## Activation boundary

This build does not:

- apply `migrations/ocu_sci_008_durable_sessions.sql`;
- change production environment variables;
- produce or invent an OCU-SCI-007 evidence artifact;
- turn learner session writes on;
- enable Calyx model calls;
- enable publication;
- enable Candidate Knowledge writes.

Operational activation remains blocked until the canonical frontend/backend deployment produces a passing OCU-SCI-007 artifact and its independently validated SHA-256 evidence ID is recorded.
