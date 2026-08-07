# OCU-SCI-008 — Durable Session Foundation

## Status

Implementation foundation only. The migration, repository, and activation gate are present in code, but the durable repository is deliberately **not wired into any `/api/learning/*` route** in this build.

The current production release contract remains read-only.

## Why this build exists

The read-only University path is already implemented and has a production-verification harness. The next eventual capability is durable learner sessions, instructor review, and revision history. Preparing those contracts now reduces post-cutover risk while preserving the existing governance gate.

## Database schema

`migrations/ocu_sci_008_durable_sessions.sql` defines:

- `oc_university.lab_sessions`
- `oc_university.session_events`
- `oc_university.session_reviews`

### Structural safeguards

The schema enforces at the database level:

- `publication_allowed = FALSE`
- `automatic_candidate_knowledge = FALSE`
- `human_review_required = TRUE`
- review records cannot claim Candidate Knowledge promotion
- review records cannot claim publication
- event sequence uniqueness
- event/session revision uniqueness
- valid scientific-method stages only
- valid session lifecycle states only

Approval for Candidate Knowledge **consideration** is represented separately from actual Candidate Knowledge promotion.

## Optimistic concurrency

`app/university/durable_repository.py` requires every event append to present the learner session revision last observed by the caller.

A stale revision raises:

`REVISION_CONFLICT`

and no event is committed. This protects a learner notebook from silent last-write-wins overwrites across browser tabs, retries, or concurrent clients.

## Ownership isolation

The durable repository records a `learner_actor`. Reads and writes require that actor unless a later caller explicitly passes a privileged operational context.

No public or learner-facing route is connected to this repository in OCU-SCI-008.

## Activation gate

`durable_sessions_enabled()` is fail-closed and requires all of the following:

```text
OCU_UNIVERSITY_ENABLED=true
OCU_UNIVERSITY_SESSION_WRITES_ENABLED=true
OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED=true
OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED=true
OCU_UNIVERSITY_RELEASE_EVIDENCE_ID=<non-empty evidence identifier>
```

The final two controls encode the sequencing requirement established by OCU-SCI-007: durable sessions must not be activated until the read-only production release has been verified and its evidence artifact recorded.

The existence of these environment variables does not itself prove verification. Operational activation still requires a reviewed production evidence artifact.

## Migration application boundary

This build adds the SQL migration file but does not apply it to Neon or any other database.

Applying the migration is a separate operational action because it changes persistent infrastructure. That action should occur only after:

1. the read-only production deployment has passed OCU-SCI-007;
2. the database target is confirmed;
3. migration backup/rollback expectations are reviewed; and
4. the activation build wires the repository behind authenticated routes.

## Validation

Deterministic validation is provided by:

```bash
python scripts/validate_university_durable_migration.py
python -m unittest tests/test_university_durable_foundation.py
python -m py_compile app/university/durable_config.py app/university/durable_repository.py
```

GitHub Actions workflow:

`OCU University Durable Foundation`

The migration validator checks that the database-level scientific and publication safeguards remain present.

## Deliberately not implemented

OCU-SCI-008 does not:

- apply the migration;
- alter the current release-readiness endpoint;
- change `process_local_memory` capability reporting;
- wire durable storage into `UniversitySessionService`;
- expose new learner write endpoints;
- enable session writes;
- enable instructor review routes;
- invoke Calyx;
- write Candidate Knowledge;
- publish learner conclusions.

## Next activation build

After a passing OCU-SCI-007 production evidence artifact exists, the next build may implement **OCU-SCI-009 — Durable Session Activation and Instructor Review API**.

That build should:

1. apply or verify the reviewed database migration;
2. replace process-local persistence behind the existing service interface;
3. require `expected_revision` on every mutation;
4. add authenticated submit/review endpoints;
5. maintain learner ownership isolation;
6. keep publication and Candidate Knowledge promotion outside the University transaction;
7. update release-readiness and frontend capability reporting only after database validation passes.
