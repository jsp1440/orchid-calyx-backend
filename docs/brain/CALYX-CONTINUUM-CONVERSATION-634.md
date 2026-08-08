# CALYX-634 — Ask the Continuum conversational evidence access

Date: 2026-08-08
Depends on: CALYX-631 registered dataset rows, CALYX-617 Scientific Computing, CALYX-453 Research Station, CALYX-448 Literature Intelligence, Evidence Retrieval 085B, Mission Control chat 003B.
Status: exact-head backend validation complete and Research Station conversational frontend validated; both review-ready and unmerged. No deployment, publication, external communication, or Knowledge Graph mutation authorized.

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

## Backend validation

Dedicated CI compiles the conversational surface and runs focused CALYX-634 service/API tests, Mission Control 003B chat regressions, Evidence Retrieval 085B regressions, permanent non-authority source assertions, Ruff, and diff hygiene.

Validation history:

- an initial legacy Chat API failure was formatting-only and was corrected without semantic change;
- a mistaken historical Evidence Retrieval test filename in the new workflow was replaced with the canonical `tests/test_build_085b_hybrid_retrieval.py`;
- behavioral/regression validation passed `18 passed`;
- permanent Ask-the-Continuum non-authority assertions passed;
- remaining Ruff `UP037`/`ISC004` issues were formatter-corrected;
- final user-authored backend head `8a2115f401f928b94675deb9fabc5e90b1e75904` passed CALYX Continuum Conversation 634, Mission Control 003B Chat API, and CALYX Workflow Governance Audit;
- backend PR `jsp1440/orchid-calyx-backend#634` is mergeable and review-ready.

## Research Station conversation surface — RS-7

Research Station PR `jsp1440/orchid-research-station#7` adds the first usable project-scoped **Ask Calyx** interface on top of CALYX-634.

Delivered frontend behavior:

- project detail exposes an `Ask Calyx` action;
- route `/workspace/calyx/$projectId` loads the current project and prefills its research question when present;
- questions are sent through the centralized authenticated client with `active_project_id` as context;
- answers display epistemic status, evidence/excerpt counts, and the `ASK_THE_CONTINUUM_FIRST` policy;
- evidence cards display only backend-authorized excerpts and supplied citation/review/verification metadata;
- retrieval tool trace is inspectable;
- the UI visibly states that model-memory fallback, scientific publication authority, and Knowledge Graph mutation are disabled.

RS-7 exact head `569f8d193325caf7dba850f85ec5cd6654013bf2` passed canonical formatting, format verification, both lint stages, the frontend test suite, and production build. PR #7 is mergeable and review-ready.

## RS-6 integration status

The Research Station registered-row frontend slice, PR `jsp1440/orchid-research-station#6`, passed its full formatting, lint, test, and production-build gate on head `2741f4d5376cafaed8c780546c59a2e85464a593` and is review-ready. It remains unmerged and non-production behind backend dependency governance.

## Next conversational priorities

1. add governed Knowledge Graph read tools to the conversation planner rather than embedding graph facts into model memory;
2. add explicit source/tool selection and contradiction reporting;
3. add conversation/session persistence beyond in-process transcript memory;
4. add taxon/document context selectors as governed routing inputs;
5. only after these foundations are stable, introduce a separately governed generative synthesis provider with evidence packets as mandatory input.

No scientific fact becomes canonical merely because Calyx discussed it in conversation.
