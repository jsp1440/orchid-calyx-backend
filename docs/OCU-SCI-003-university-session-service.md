# OCU-SCI-003 — University Session Service

## Status

Feature-flagged backend prototype. Disabled by default.

## Endpoints

All routes are nested under the existing Calyx `/api` router:

- `GET /api/learning/capabilities`
- `GET /api/learning/catalog`
- `GET /api/learning/chapters/{chapter_id}`
- `GET /api/learning/laboratories/{laboratory_id}`
- `POST /api/learning/sessions`
- `GET /api/learning/sessions/{session_id}`
- `POST /api/learning/sessions/{session_id}/events`

The capability endpoint is always available and reports whether the prototype is enabled. Catalog and content endpoints return 404 while disabled. Session endpoints additionally require authenticated owner/API-key context and the explicit session-write flag.

## Feature flags

```text
OCU_UNIVERSITY_ENABLED=false
OCU_UNIVERSITY_SESSION_WRITES_ENABLED=false
```

Both default to false. Session writes require both to be true.

## Persistence boundary

OCU-SCI-003 uses process-local memory only. It is intentionally nondurable:

- sessions disappear when the process restarts;
- no migrations or database tables are added;
- no learner record should be represented as permanently stored;
- this store is suitable only for development and controlled prototype review.

Durable persistence requires a later reviewed migration.

## Scientific and governance boundaries

The service cannot:

- publish a learner conclusion;
- write to Candidate Knowledge;
- invoke Calyx or another model;
- represent curated fixtures as live Continuum data;
- skip human review;
- advance more than one scientific-method stage in a single event.

Every session is created with:

```json
{
  "publication_allowed": false,
  "automatic_candidate_knowledge": false,
  "human_review_required": true
}
```

## Curated content

The prototype serves one Book in the Brain chapter and one laboratory:

- `BITB-CHAPTER-ORCHID-FLOWERING-001`
- `OCU-LAB-FAILURE-TO-BLOOM-001`

These are local fixtures derived from the OCU-SCI-001 and OCU-SCI-002 contracts. They retain explicit epistemic labels and do not claim live Knowledge Graph, Conservatory, Atlas, or Literature integration.

## Validation

```bash
python -m unittest tests/test_university_session_service.py
```

## Next backend step

After review of the prototype:

1. Add durable session/event tables with row-level ownership.
2. Import canonical schemas from the Brain release rather than duplicating fixtures.
3. Add instructor review endpoints.
4. Add idempotency keys and optimistic concurrency.
5. Connect evidence through read-only service adapters.
6. Keep publication and Candidate Knowledge transitions in separate governed services.
