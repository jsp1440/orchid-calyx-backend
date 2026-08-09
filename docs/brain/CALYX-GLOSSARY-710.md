# CALYX-GLOSSARY-710 — Governed Scientific Language Intake

## Objective

Operationalize issue #710 without creating a second concept registry. Literature-derived vocabulary remains candidate evidence until human review resolves it against the canonical `app.concepts` identity/lexical services.

## Delivered

- deterministic candidate identity from normalized term + exact source URI/revision/checksum/evidence-span/language;
- idempotent replay;
- resolution through the existing `ConceptRegistryService.search_concepts()` contract;
- explicit states: `UNRESOLVED`, `CANDIDATES`, `AMBIGUOUS`, `MATCHED_PENDING_REVIEW`, `REVIEWED_MATCH`, `NEW_CONCEPT_CANDIDATE`, `REJECTED`;
- no automatic conversion of exact lexical resolution into canonical approval;
- human-only reviewed-match decision requiring an existing canonical concept;
- canonical glossary projection that reads labels and audience-specific definitions from `app.concepts` rather than duplicating them;
- deterministic concept-linked figure requests for diagram/sketch/color illustration/photo set/animation/comparison plate/dissection;
- additive PostgreSQL tables under `oc_concepts` for candidates and figure requests;
- authenticated `/api/concepts/glossary/*` APIs using the existing owner/API-key dependency;
- focused service regressions and read-only CI.

## Provenance contract

Candidate identity binds the exact source URI, source revision ID, source SHA-256, evidence-span ID, normalized term, and language. Repeated intake of the same evidence is idempotent. A term seen in a different source revision or evidence span is a distinct provenance-bearing candidate.

## Canonical identity boundary

`ConceptRegistryService` remains authoritative. This layer does not create a concept, label, definition, or canonical concept status. A lexical `RESOLVED` result becomes only `MATCHED_PENDING_REVIEW`. Ambiguity and unresolved states are preserved rather than guessed.

Human review may mark a candidate as:

- `REVIEWED_MATCH` with an existing concept ID;
- `NEW_CONCEPT_CANDIDATE` without creating the concept; or
- `REJECTED`.

Actual concept creation/activation remains governed by the existing Concept Registry workflow.

## Figure boundary

Figure requests are production aids linked to canonical concept identity. They are explicitly not scientific evidence and do not authorize generation, publication, provider access, or vendor-specific automation. The existing Figure Labs/manual-provider workflow can consume the queue later without granting the glossary layer scientific authority.

## Database migration

`migrations/20260808_calyx_glossary_candidate_queue.sql` is additive and is not applied by this PR. It creates `oc_concepts.glossary_candidates` and `oc_concepts.glossary_figure_requests` with constrained state/type values and concept foreign keys.

## Permanent non-authorities

This slice does not:

- automatically create or activate canonical concepts;
- invent definitions or pronunciation;
- choose an ambiguous concept match;
- publish candidates or figures;
- mutate the production Knowledge Graph;
- send figure work to a provider;
- deploy production;
- apply the migration;
- merge itself.

## Validation status

Dedicated workflow: `CALYX Glossary 710 Validation`.

The repository-wide hosted-runner incident #481 may cause jobs to terminate before step 1 with `steps=null`. Such a run is infrastructure evidence only and is not a compile/lint/test verdict. Keep the PR draft and unmerged until this exact head receives executable validation.
