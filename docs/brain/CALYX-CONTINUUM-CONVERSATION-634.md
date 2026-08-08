# CALYX-634 — Ask the Continuum conversational evidence access

Date: 2026-08-08
Depends on: CALYX-631 registered dataset rows, CALYX-617 Scientific Computing, CALYX-453 Research Station, CALYX-448 Literature Intelligence, Evidence Retrieval 085B, Mission Control chat 003B.
Status: bounded implementation behavior validated; exact-head rerun pending after formatter-authored commit. No merge, deployment, publication, external communication, or Knowledge Graph mutation authorized.

## Goal

Turn the existing Mission Control transcript surface into a real read-only conversational entry point to Orchid Continuum evidence.

Before this build, `/brain/mission-control/chat/messages` recorded an operator message and `/replies` accepted a separately supplied Calyx reply. The chat surface itself did not query the Continuum and therefore could not answer a scientific question.

CALYX-634 adds a protected `POST /brain/mission-control/chat/ask` route that performs:

`operator question -> authenticated owner scope -> hybrid Evidence Retrieval -> authorized evidence envelope -> extractive Calyx answer -> auditable two-sided transcript`

## Ask the Continuum policy

The first conversational implementation is deliberately retrieval-grounded and extractive. It does not pretend that a general LLM synthesis provider exists in the backend.

Each answer permanently records:

- `answering_policy=ASK_THE_CONTINUUM_FIRST`;
- `model_knowledge_used=false`;
- `scientific_interpretation_generated=false`;
- `human_review_required_for_scientific_conclusion=true`;
- `scientific_publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

If the Continuum returns no eligible evidence, Calyx says so and explicitly does not substitute general model knowledge.

## Evidence preservation

The response preserves, per result:

- retrieval result ID and rank;
- fused retrieval score;
- object type and title;
- only the excerpt already authorized by Evidence Retrieval display policy;
- citation metadata and source locator;
- reliability signals;
- review and verification states;
- temporal status;
- display policy;
- collection membership.

The answer text uses at most the first three authorized evidence excerpts and truncates long excerpts for conversational display. Citation/provenance records remain the authority.

## Epistemic states

The API distinguishes:

- `continuum_evidence` — eligible evidence and at least one authorized excerpt were retrieved;
- `continuum_evidence_metadata_only` — eligible records exist but display policy does not permit an excerpt suitable for synthesis;
- `unknown` — no eligible Continuum evidence was returned.

These states are not confidence scores and do not convert retrieval into reviewed scientific knowledge.

## Context contract

The request accepts optional context identifiers:

- active project ID;
- active taxon ID;
- active document ID.

CALYX-634 preserves these identifiers in the response for later contextual tool routing. This first slice does not silently broaden or mutate scientific scope based on them.

## Authentication and transcript behavior

`/chat/ask` requires the existing owner/API-key authentication dependency. A successful call records both the operator question and the generated Calyx evidence answer in the existing auditable transcript.

Legacy transcript/message/reply routes are preserved for compatibility. Consequential action controls remain unchanged: no automatic merge, deploy, publication, external communication, permission change, or governance change is introduced.

## Validation

Dedicated CI compiles the new surface and runs:

- CALYX-634 focused service/API tests;
- Mission Control 003B chat regressions;
- Evidence Retrieval 085B regressions;
- permanent non-authority source assertions;
- Ruff and diff hygiene.

Focused tests cover grounded evidence answers, no-evidence fail-closed behavior, metadata-only display-policy behavior, authenticated `/ask`, transcript recording, and owner-scope rejection.

### Validation evidence

- initial legacy Chat API failure was formatting-only; Ruff-required line wrapping was applied without semantic change;
- corrected legacy Mission Control 003B chat lane passed;
- governance audit passed;
- CALYX-634 behavior plus Mission Control and Evidence Retrieval regressions passed `18 passed` on the corrected implementation;
- permanent Ask-the-Continuum non-authority assertions passed;
- the remaining failure on that run was changed-surface Ruff (`UP037`, `ISC004`), corrected by formatter commit `fbc912549867b854f4e663f22d2bb891079607f3`;
- GitHub marked workflows on that Copilot-authored formatter head `action_required`; this documentation commit intentionally creates a user-authored exact head so normal Actions validation can execute again.

## RS-6 integration status

The Research Station registered-row frontend slice, PR `jsp1440/orchid-research-station#6`, passed its full formatting, lint, test, and production-build gate on head `2741f4d5376cafaed8c780546c59a2e85464a593` and was moved from draft to review on 2026-08-08. It remains unmerged and non-production behind backend dependency governance.

## Next conversational priorities

1. validate CALYX-634 exact head;
2. add governed Knowledge Graph read tools to the conversation planner rather than embedding graph facts into model memory;
3. add explicit source/tool selection and contradiction reporting;
4. add conversation/session persistence beyond in-process transcript memory;
5. add a Research Station/Continuum frontend Calyx conversation surface;
6. only after these foundations are stable, introduce a separately governed generative synthesis provider with evidence packets as mandatory input.

No scientific fact becomes canonical merely because Calyx discussed it in conversation.
