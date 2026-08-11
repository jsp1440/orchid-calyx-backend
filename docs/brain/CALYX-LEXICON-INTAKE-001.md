# CALYX-LEXICON-INTAKE-001 — Governed glossary reconciliation intake

## Purpose

Convert the reconciled 2026-08-09 Illustrated Orchid Lexicon / Figure Labs workbook into a deterministic, provenance-locked staging queue without prematurely promoting weak glossary content or spending Figure Labs credits.

## Source

- File: `Orchid_Continuum_FigureLabs_Vision_Glossary_Queue_2026-08-09.xlsx`
- Sheet: `Figure Queue`
- SHA-256: `fe0dfed4e6cd5e330ccba94967b4541f475389bb89065479ea2296fdce83e687`
- Working rows: 420

The source workbook remains the evidentiary origin for this staging classification. The compressed CSV in `app/lexicon/intake_seed.py` is a deterministic transport representation, not a replacement scientific authority.

## Reconciliation state

- 420 glossary terms total
- 221 definitions present → `READY_FOR_CONCEPT_REVIEW`
- 199 placeholder definitions → `BLOCKED_DEFINITION`
- 10 exact existing asset matches → `EXISTING_ASSET_VERIFY`
- 27 probable asset matches → `PROBABLE_ASSET_VERIFY`
- 383 missing illustrations → `FIGURE_GENERATION_HOLD`

### Critical finding

All 37 terms with exact or probable existing illustration matches are among the 199 placeholder-definition records. Illustration coverage therefore does **not** imply scientific-definition readiness. Existing visual assets must not bypass concept/definition review.

## Governance decisions

1. This intake is read-only.
2. No intake row automatically creates or activates a Core Concept Registry concept.
3. Placeholder definitions block concept import/promotion.
4. The 383 missing-figure rows remain on generation hold until the Calyx Vision requirements review is completed and the figure identity/provenance contract is frozen.
5. Existing/probable assets require identity, provenance, duplicate/conflict, and scientific-content verification before canonical attachment.
6. No automatic publication, taxonomy activation, Candidate Knowledge promotion, Knowledge Graph mutation, or Figure Labs execution is authorized.

## API

Owner/API-key authenticated read-only endpoints:

- `GET /api/lexicon/intake/status`
- `GET /api/lexicon/intake/items`
- `GET /api/lexicon/intake/items/{glossary_id}`

Filtering supports query text, concept-intake state, figure state, priority, and bounded result limits.

## Validation contract

Automated validation must prove:

- the embedded manifest decodes to exactly 420 unique glossary IDs;
- field order matches the declared manifest schema;
- all reconciliation counts match the source-derived summary;
- the 37 existing/probable assets remain definition-blocked;
- source SHA-256 metadata remains fixed;
- generation/promotion/publication safeguards remain enabled;
- the read-only routes are mounted beneath the canonical `/api/lexicon` facade.

## Next governed work

After this intake is canonical, the next scientific-content lane is definition enrichment/review. Figure generation remains gated on the separate live Calyx Vision requirements conversation and figure-specification freeze.
