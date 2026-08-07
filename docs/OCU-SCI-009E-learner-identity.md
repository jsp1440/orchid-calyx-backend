# OCU-SCI-009E — Backend-verifiable learner identity

## Status

Prepared identity integration only. No production learner-auth flag, durable-session flag, database migration, publication path, Candidate Knowledge write, or Calyx model call is enabled by this build.

## Purpose

Use the Orchid Continuum frontend's existing Supabase Auth account system as the learner identity provider for University sessions. Do not create a second University account system and do not conflate learner authentication with scientific-review authority.

## Learner verification

When `OCU_UNIVERSITY_LEARNER_AUTH_ENABLED=true`, University session routes require a Supabase access token in the `Authorization: Bearer` header.

The backend validates that token against the configured Supabase Auth user endpoint using:

- `OCU_SUPABASE_URL`
- `OCU_SUPABASE_ANON_KEY`

The verification request is executed outside the FastAPI event loop.

Only the stable Supabase user UUID is retained in University identity context, represented as:

`supabase:<uuid>`

The University service does not persist the learner's email address, profile metadata, or access token.

## Fail-closed behavior

Learner-auth failures produce explicit authentication/service errors for:

- missing bearer session;
- missing verifier configuration;
- invalid or expired token;
- unavailable identity provider;
- malformed or missing stable user UUID.

Once learner auth is enabled, owner/API-key identity is no longer accepted as a learner identity on session routes.

Before learner auth is enabled, the existing process-local prototype owner/API-key contract remains available for compatibility. This fallback cannot open durable mode because the durable activation gate now independently requires learner authentication.

## Durable activation gate

`durable_sessions_enabled()` now requires all of:

- University enabled;
- session writes enabled;
- learner auth enabled;
- durable-session flag enabled;
- prior read-only release verified;
- valid OCU-SCI-007 SHA-256 release-evidence identifier.

Valid release evidence cannot bypass missing learner identity verification.

Release contract version advances to `OCU-RELEASE-003` and exposes non-sensitive `learner_auth_enabled` state in both release-readiness and capability responses.

## Reviewer separation

Learner authentication grants no scientific-review capability.

Instructor review continues to use the separate Mission Control `AccessPrincipal` dependency and its qualification/capability policy:

- learning decisions require qualified `review.science`;
- Candidate Knowledge consideration requires qualified `review.expert`;
- administrator or API-key status alone does not imply scientific-review authority.

## Privacy and security boundaries

- No Supabase access token is stored in University records.
- No learner email is stored in University records by this integration.
- The stable UUID-derived actor is used for ownership isolation.
- Identity-provider failures fail closed rather than falling back to owner/API-key identity after learner auth is enabled.
- Publication and Candidate Knowledge promotion remain outside the University transaction.

## Required frontend follow-up

The learner notebook must pass its existing Supabase Auth `session.access_token` on create, resume, event, and submit requests and must remain closed when the user is not signed in.

This follow-up must not add reviewer controls to the learner identity path.
