# CALYX-LEXICON-LIVE-002 — Famous UI to canonical backend runtime contract

Date: 2026-08-11

## Status

Current-main candidate. The Famous-derived Lexicon presentation is retained in the public frontend, while scientific authority remains the Orchid Continuum Concept Registry (`oc_concepts`).

## Runtime contract

- `GET /api/lexicon/entries/{slug}` resolves a page directly to an ACTIVE + APPROVED concept through an APPROVED label.
- Slug resolution is an exact normalized-label lookup and is independent of broad-search result limits.
- Public Lexicon search matches APPROVED labels and APPROVED definitions only.
- `GET /api/lexicon/concepts/{concept_id}` remains the canonical approved concept lookup used by Matrix concept bindings.
- Capabilities advertise the direct canonical entry route.
- Missing canonical fields remain legitimate; the backend does not invent Famous-era enrichment.

## Famous migration boundary

The Famous/Lovable export is migration and presentation source material, not a scientific write authority. Frontend migration overlays may preserve narrow presentation fields, but Famous definitions, evidence-bearing prose, relationships, diagnostic states, literature claims, review status, or identity do not become canonical science merely because they existed in the prototype.

## Matrix interoperability

The current Matrix lineage stores explicit reviewed Concept Registry UUID bindings. Direct Lexicon slug access does not fuzzy-match or mutate those mappings. Matrix concept readiness and reviewed registry derivation remain separate governed workflows.

## Governance

- public entries require ACTIVE + APPROVED concepts;
- labels and searchable definitions require APPROVED review state;
- no automatic concept promotion;
- no automatic publication;
- no legacy Famous/Supabase scientific writes;
- no taxonomy or Knowledge Graph mutation;
- no fallback content is represented as reviewed canonical evidence.

## Validation

Dedicated `CALYX Lexicon Live 002 Validation` compiles and executes the direct-entry contract, adjacent canonical Lexicon/Matrix registry regressions, Ruff, format, and diff hygiene. At creation time private GitHub Actions incident #481 still prevents hosted jobs from obtaining executable steps; zero-step failures are infrastructure evidence, not a green or red product-test result.
