# OCU-SCI-009F — My Investigations

## Purpose

Remove the requirement that a learner manually retain an opaque University session ID in order to resume scientific work.

## Contract

`GET /api/learning/sessions`

The endpoint is available only through the verified University learner identity path and only when the durable University gate is open. It returns session summaries owned by the authenticated Supabase actor.

### Privacy and authorization

- ownership is enforced inside the SQL query with `learner_actor = authenticated_actor`
- the service does not fetch all sessions and filter afterward
- no learner email, Supabase token, event payload, review note, reviewer identity, or other learner identifier is returned
- owner/API-key prototype identities are rejected by the discovery endpoint
- reviewer qualification remains a separate Mission Control capability path

### Pagination

The endpoint uses bounded keyset pagination ordered by `(updated_at DESC, session_id DESC)` with a maximum page size of 50. The cursor contains only the last visible update timestamp and session UUID and is validated fail-closed.

### Database

No migration is required. OCU-SCI-008 already created `university_lab_sessions_actor_idx` on `(learner_actor, updated_at DESC)`, which supports the ownership-first query.

## Governance boundary

This build does not activate production University flags, run a migration, publish learner work, promote Candidate Knowledge, enable Calyx model calls, or grant reviewer authority.
