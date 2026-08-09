# CALYX-GLOSSARY-710 — Governed Scientific Language Intake

## Objective

Operationalize issue #710 without creating a second concept registry. Literature-derived vocabulary remains candidate evidence until human review resolves it against the canonical `app.concepts` identity/lexical services.

## Delivered

- deterministic candidate identity from normalized term + exact source URI/revision/checksum/evidence-span/language;
- idempotent replay, including normalized surrounding whitespace for bounded provenance fields;
- resolution through the existing `ConceptRegistryService.search_concepts()` contract;
- explicit states: `UNRESOLVED`, `CANDIDATES`, `AMBIGUOUS`, `MATCHED_PENDING_REVIEW`, `REVIEWED_MATCH`, `NEW_CONCEPT_CANDIDATE`, `REJECTED`;
- preservation of candidate concept IDs from both exact IDs and lexical candidate matches, without guessing which candidate is correct;
- no automatic conversion of exact lexical resolution into canonical approval;
- human-only reviewed-match decision requiring an existing canonical concept;
- terminal review-decision immutability: exact replay is idempotent and a conflicting replacement fails closed;
- append-only, digest-keyed review events written transactionally with the terminal candidate decision;
- canonical glossary projection that reads labels and audience-specific definitions from `app.concepts` rather than duplicating them;
- deterministic concept-linked figure requests for diagram/sketch/color illustration/photo set/animation/comparison plate/dissection;
- persistent database constraints that keep automatic concept promotion, Knowledge Graph publication, figure-evidence status, automatic figure generation, and automatic figure publication false;
- authenticated `/api/concepts/glossary/*` APIs using the existing owner/API-key dependency;
- focused service regressions and read-only CI.

## Provenance contract

Candidate identity binds the normalized source URI, source revision ID, source SHA-256, evidence-span ID, normalized term, and language. Repeated intake of the same evidence is idempotent. A term seen in a different source revision or evidence span is a distinct provenance-bearing candidate.

A `CANDIDATES` or `AMBIGUOUS` lexical result retains every concept ID supplied by the canonical search result. It never silently collapses that set to a single concept. A `RESOLVED` lexical result becomes only `MATCHED_PENDING_REVIEW`.

## Canonical identity boundary

`ConceptRegistryService` remains authoritative. This layer does not create a concept, label, definition, or canonical concept status. Human review may mark a candidate as:

- `REVIEWED_MATCH` with an existing concept ID;
- `NEW_CONCEPT_CANDIDATE` without creating the concept; or
- `REJECTED`.

Once one of those terminal decisions exists, an identical replay returns the existing decision. A different later decision is rejected with `GLOSSARY_REVIEW_DECISION_IMMUTABLE`. The PostgreSQL repository applies the terminal-state guard in the same UPDATE predicate and records the accepted decision in `oc_concepts.glossary_candidate_review_events` under a deterministic SHA-256 decision digest. This protects the governance boundary against concurrent replacement as well as process-local mistakes.

Actual concept creation/activation remains governed by the existing Concept Registry workflow.

## Figure boundary

Figure requests are production aids linked to canonical concept identity. They are explicitly not scientific evidence and do not authorize generation, publication, provider access, or vendor-specific automation. The existing Figure Labs/manual-provider workflow can consume the queue later without granting the glossary layer scientific authority.

## Database migration

`migrations/20260808_calyx_glossary_candidate_queue.sql` is additive and is not applied by this PR. It creates:

1. `oc_concepts.glossary_candidates` for provenance-bearing candidate state;
2. `oc_concepts.glossary_candidate_review_events` for append-only terminal review evidence; and
3. `oc_concepts.glossary_figure_requests` for canonical-concept-linked production requests.

Database CHECK constraints enforce the permitted candidate states and figure types and permanently hold the automatic authority flags false.

## Permanent non-authorities

This slice does not:

- automatically create or activate canonical concepts;
- invent definitions or pronunciation;
- choose an ambiguous concept match;
- replace an accepted terminal human review decision;
- publish candidates or figures;
- mutate the production Knowledge Graph;
- send figure work to a provider;
- deploy production;
- apply the migration; or
- merge itself.

## Validation status

Dedicated workflow: `CALYX Glossary 710 Validation`.

The workflow compiles and Ruff-checks the glossary runtime/repository/router surfaces, runs the focused glossary regressions plus existing BUILD-SEM-002B lexical-service regressions, statically asserts the non-authority and immutable-review contracts, and runs diff hygiene.

The repository-wide hosted-runner incident #481 may cause jobs to terminate before step 1 with `steps=null`. Such a run is infrastructure evidence only and is not a compile/lint/test verdict. Keep the PR draft and unmerged until this exact head receives executable validation.
