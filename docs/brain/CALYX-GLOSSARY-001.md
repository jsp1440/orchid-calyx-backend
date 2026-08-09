# CALYX-GLOSSARY-001 — Scientific Language Layer

## Purpose

This build turns the existing Canonical Scientific Concept Registry into an operational glossary-facing language layer without creating a second source of truth.

The Concept Registry remains authoritative for concept identity, labels, definitions, lifecycle, and review state. The new glossary layer adds only two bounded concerns:

1. durable intake of vocabulary candidates discovered by literature or other evidence-bearing sources;
2. a governed queue of figure requests attached to canonical concepts.

## Data flow

```text
Literature / source text
  -> extracted term
  -> deterministic glossary candidate
  -> existing Concept Registry search
  -> unresolved / candidates / ambiguous / exact match pending review
  -> human review
  -> existing canonical concept workflow

Canonical concept
  -> labels + definitions from oc_concepts
  -> glossary projection
  -> optional figure request queue
```

No candidate becomes canonical knowledge automatically.

## Candidate identity

Candidate IDs are UUIDv5 values derived from a SHA-256 fingerprint over:

- normalized term;
- language;
- source kind;
- source hash;
- optional source span;
- canonicalized source locator.

Exact replay therefore reuses the same candidate identity. Repeated intake updates `last_seen_at` instead of creating duplicate candidate rows.

## Resolution semantics

The existing `ConceptRegistryService.search_concepts()` is authoritative for lexical lookup.

- `RESOLVED` becomes `MATCHED_PENDING_REVIEW` and stores the candidate concept ID.
- `AMBIGUOUS` stays ambiguous and stores no guessed concept ID.
- `CANDIDATES` stays a candidate set.
- `UNRESOLVED` remains unresolved.

Later human review may mark a candidate as a reviewed match, new-concept candidate, or rejected. This build intentionally does not implement automatic promotion.

## Glossary projection

`GET /api/concepts/glossary/{id-or-uri}/entry` projects the canonical concept together with:

- preferred labels;
- all lexical labels;
- all audience-specific definitions;
- current figure requests;
- an explicit pronunciation placeholder.

Pronunciation is deliberately `NOT_YET_IMPLEMENTED`; no phonetic or audio value is invented.

## Figure queue

Figure requests are deterministic UUIDv5 records linked to canonical concepts. Supported request types are:

- DIAGRAM
- SKETCH
- COLOR_ILLUSTRATION
- PHOTO_SET
- ANIMATION
- COMPARISON_PLATE
- DISSECTION

Each request stores title, caption, generation prompt, priority, provenance, review requirement, and a permanent `scientific_evidence=false` marker. Generated artwork may illustrate evidence but is not itself primary scientific evidence.

## API surface

Authenticated through the existing owner-session/API-key boundary:

- `POST /api/concepts/glossary/candidates`
- `GET /api/concepts/glossary/candidates`
- `GET /api/concepts/glossary/figures`
- `GET /api/concepts/glossary/{id-or-uri}/entry`
- `POST /api/concepts/glossary/{concept_id}/figure-requests`

The router is added inside the existing Concept Registry router so no parallel application or source of truth is introduced.

## Persistence

Additive migration:

`migrations/20260808_glossary_scientific_language.sql`

Tables:

- `oc_concepts.glossary_candidates`
- `oc_concepts.glossary_figure_requests`

No existing concept, ontology, literature, reasoning, or Knowledge Graph table is altered.

## Governance invariants

- no automatic concept creation or activation;
- no automatic Knowledge Graph publication;
- ambiguity is never guessed away;
- source hash and locator are required for candidate intake;
- source spans must be complete and valid when supplied;
- definitions remain owned by `oc_concepts.concept_definitions`;
- labels remain owned by `oc_concepts.concept_labels`;
- figure prompts are production instructions, not scientific evidence;
- human review remains required for canonical promotion and figure approval.

## Validation

`tests/test_calyx_glossary_001.py` covers:

- deterministic candidate identity and idempotent replay;
- exact-match review blocking;
- preservation of ambiguity/candidate states;
- fail-closed source-span validation;
- glossary projection reuse of canonical lexical records;
- deterministic figure requests and evidence separation.

Dedicated workflow: `.github/workflows/calyx-glossary-001-validation.yml`.

At the time of implementation, repository-wide GitHub-hosted runner allocation is tracked by issue #481. This PR must remain draft/unmerged until executable CI produces actual steps and the dedicated validation passes.

## Next slices

After this foundation is validated:

1. connect Literature Intelligence unknown-term extraction directly to glossary candidate intake;
2. add reviewed candidate state transitions and explicit canonical promotion through existing Concept Registry governance;
3. add pronunciation records (IPA/phonetic/audio provenance) without inventing pronunciations;
4. add image-database matching and approved asset linkage;
5. add Figure Labs / external generation workflow adapters while preserving human approval;
6. expose study-card/download/quiz projections as consumers of the same canonical concepts.
