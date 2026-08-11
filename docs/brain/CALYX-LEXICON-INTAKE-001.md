# CALYX-LEXICON-INTAKE-001 — Governed glossary reconciliation intake

## Purpose

Convert the reconciled 2026-08-09 Illustrated Orchid Lexicon / Figure Labs workbook into a deterministic, provenance-locked staging queue without prematurely promoting weak glossary content or spending Figure Labs credits.

## Source

- File: `Orchid_Continuum_FigureLabs_Vision_Glossary_Queue_2026-08-09.xlsx`
- Sheet: `Figure Queue`
- SHA-256: `fe0dfed4e6cd5e330ccba94967b4541f475389bb89065479ea2296fdce83e687`
- Working rows: 420

The source workbook remains the evidentiary origin for this staging classification. The compressed CSV in `app/lexicon/intake_seed.py` is a deterministic transport representation, not a replacement scientific authority.

## Corrected reconciliation state

A review of the workbook content showed that the original `Definition Status` label was insufficient to determine scientific readiness. The 221 rows previously classified as definitions present are synthetic `botanical_term_#` placeholders with generic expansion text, not canonical botanical concepts.

The governed intake therefore classifies the current source as:

- 420 rows total
- 199 real botanical term names with placeholder definitions → `BLOCKED_DEFINITION`
- 221 synthetic `botanical_term_#` placeholders with placeholder definitions → `BLOCKED_PLACEHOLDER_TERM`
- 0 rows → `READY_FOR_CONCEPT_REVIEW`
- 10 exact existing asset matches → `EXISTING_ASSET_VERIFY`
- 27 probable asset matches → `PROBABLE_ASSET_VERIFY`
- 383 missing illustrations → `FIGURE_GENERATION_HOLD`

### Critical findings

1. No current workbook row is scientifically ready for automatic Concept Registry intake.
2. All 37 terms with exact or probable existing illustration matches are among the 199 real-name / placeholder-definition records. Illustration coverage therefore does **not** imply scientific-definition readiness.
3. The 221 synthetic placeholder terms must be replaced by real source-backed vocabulary or removed; they may never be promoted merely because the spreadsheet calls their definitions present.

## Governance decisions

1. This intake is read-only.
2. No intake row automatically creates or activates a Core Concept Registry concept.
3. Placeholder definitions block concept import/promotion.
4. Synthetic placeholder term identities block concept import/promotion independently of definition state.
5. The 383 missing-figure rows remain on generation hold until the live Calyx Vision requirements review is completed and the figure identity/provenance contract is frozen.
6. Existing/probable assets require identity, provenance, duplicate/conflict, and scientific-content verification before canonical attachment.
7. No automatic publication, taxonomy activation, Candidate Knowledge promotion, Knowledge Graph mutation, or Figure Labs execution is authorized.

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
- 221 synthetic placeholder terms remain `BLOCKED_PLACEHOLDER_TERM`;
- 199 real named terms remain `BLOCKED_DEFINITION` until definitions are repaired;
- zero rows are `READY_FOR_CONCEPT_REVIEW`;
- the 37 existing/probable assets remain definition-blocked;
- source SHA-256 metadata remains fixed;
- generation/promotion/publication safeguards remain enabled;
- the read-only routes are mounted beneath the canonical `/api/lexicon` facade.

## Next governed work

After this intake is canonical, the next scientific-content lane is definition and term-identity enrichment under evidence/review governance. Figure generation remains gated on the separate live Calyx Vision requirements conversation and figure-specification freeze.
