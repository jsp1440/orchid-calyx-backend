# KALIX-PERSONA-001 — Named Orchid Continuum intelligence persona

## Status

Candidate implementation on `feat/kalix-build-001-context-bridge`, targeting
`oc-autonomous-integration`. Independent review is required before integration.

## Architecture decision

Kalix is a named persona layer on top of the established Calyx conversational
infrastructure. It is not a second conversational engine and does not own a
parallel scientific knowledge store.

The implementation has three bounded components:

1. `app/kalix/context_bridge.py` delegates Lexicon and Literature retrieval to
   `app.calyx_conversation.knowledge_context.build_knowledge_context`.
2. `app/kalix/persona.py` composes Kalix identity/depth metadata with the
   existing CALYX-PERSONA-005 constitution.
3. `app/kalix/routes.py` exposes authenticated `/api/kalix/status` and
   `/api/kalix/speak` routes through the existing runtime provider boundary.

## Conversation contract

`POST /api/kalix/speak` accepts:

- `message` — required user turn;
- `depth` — optional explicit grower/student/scientist/researcher register;
- `depth_hint` — optional heuristic signal used only when `depth` is absent;
- `project_id` — optional project context identifier;
- `oc_modules` — optional active-module awareness.

The response preserves both the acceptance-contract names
(`persona`, `knowledge`, `answer`, `depth_used`) and the richer Kalix
metadata needed by current clients.

## Governance

- No canonical Knowledge Graph mutation.
- No engineering dispatch authority.
- Authentication uses the existing owner/API-key verifier.
- NO_API_MODE remains provider-free.
- Provider-call accounting is explicit: deterministic execution records zero
  provider calls; an attempted generative provider records one call even when
  deterministic fallback is used.
- Kalix does not independently claim expertise; scientific capability is bounded
  by retrievable Orchid Continuum evidence, governed tools, and the inherited
  Calyx constitution.
- Maker self-certification is prohibited for the integration PR.

## Known production-readiness dependencies

- KALIX-DEPS-001 / issue #1451: add a stable LiteratureResultRepository paper-ID
  listing interface so the knowledge bridge does not depend on filesystem layout.
- KALIX-DEPS-002 / issue #1452: expose a public Lexicon concept-search interface
  so the knowledge bridge does not import a private route helper.

These are coupling hardening tasks; the current P0 path is functionally usable
but should not be treated as final production architecture until they are closed.

## Validation expectations

Before integration:

- Kalix context/persona/routes tests pass.
- Existing knowledge-context regressions pass.
- changed-file Ruff validation passes.
- Agent Security Guard and conversational/core validation remain green.
- Independent checker verifies the diff and exact head SHA before merge.
