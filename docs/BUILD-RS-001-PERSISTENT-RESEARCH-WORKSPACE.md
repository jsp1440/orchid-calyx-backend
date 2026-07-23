# BUILD-RS-001 persistent research workspace

This build adds the first production-backed Research Station module under
`/api/research/projects`. It is intentionally separate from Conservatory inventory,
public sharing, collaboration, mapping, and AI features.

## Identity and authorization

Routes reuse `verify_owner_or_api_key`. Owner sessions use the signed token subject
as `owner_subject`; API keys are an explicit privileged service identity and all
their mutations are attributed to `backend_api_key`. Normal subjects receive `404`
for projects owned by another subject. Ownership is enforced in every project and
child-record query, not trusted from request payloads.

## Persistence and audit

Apply `migrations/101_research_workspace_foundation.sql` to PostgreSQL. The migration
is additive and idempotent, creates only the `research_station` schema, and revokes
public table access. Projects use optimistic versions and soft archive. Saved
searches store normalized query state, notes remain labeled `USER_ANNOTATION`, and
taxa/documents/evidence store only canonical identifiers. Audit events are written
in the same transaction and database triggers reject updates or deletes.

The API never exposes physical deletion. Archiving blocks child mutations; restoring
retains the original project and its complete history.

## Validation and rollback

Run:

```text
python -m pytest -q tests/test_build_rs_001_research_workspace.py
python -m pytest -q tests/test_build_056_owner_authentication.py tests/test_owner_session_cors_repair.py
python -m ruff check app/research_workspace tests/test_build_rs_001_research_workspace.py
```

PostgreSQL migration integration requires an explicitly disposable
`TEST_DATABASE_URL`; production must never be used for migration tests.

Application rollback is removal of the router include and deployment of the prior
backend version. The additive schema should remain in place to preserve projects and
audit history. A later separately reviewed migration may retire it only after data
retention/export decisions are complete.
