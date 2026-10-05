# CALYX-LEXICON-INTEGRATION-001

## Mission

Migrate the Famous AI Illustrated Orchid Lexicon into the canonical Orchid Continuum without creating a competing glossary frontend or scientific data store.

## Architectural decision

The Famous AI application remains the lexicon presentation and authoring surface. Canonical scientific authority remains in Orchid Continuum services:

- Core Concept Registry: `/api/concepts`
- Lexicon facade: `/api/lexicon`
- Botanical language: `/api/scientific-interpretation/language`
- Vision-Lexicon: `/api/vision-lexicon`
- Speak with Calyx: `/api/calyx/speak/conversations`
- Literature extraction/evidence services
- Knowledge Graph

The legacy Famous Supabase-style scientific write path is not canonical and must remain disabled during migration.

## Governance

- Empty scientific fields are legitimate and must not be filled by invention.
- Public canonical lexicon records require ACTIVE concept status and APPROVED review state.
- Conversation/provider memory is not scientific evidence.
- No automatic concept promotion, publication, taxonomy activation, or Knowledge Graph mutation is introduced by this build.
- Famous migration records may remain as clearly identified fallback content until equivalent canonical records are reviewed and available.

## Implemented slice

- Added `/api/lexicon` read facade over the Core Concept Registry.
- Mapped reviewed concept labels/definitions into the richer Famous `LexiconEntry` shape.
- Preserved definition versions and source/review provenance where available.
- Added capability contract linking lexicon, Botanical Language, Vision-Lexicon, Literature, Knowledge Graph, and Calyx.
- Added focused regression tests for Famous-shape mapping and governance boundaries.
- Definition versions retain the existing display citation list and expose source-provided DOI, PMID, or ISBN identifiers plus exact evidence IDs/hashes, confidence, and uncertainty as `citation_identity`. Missing identity is not synthesized; non-bibliographic identifiers and private storage locations are not projected.

## Frontend integration contract

The canonical frontend migration preserves the Famous illustrated lexicon experience under `/lexicon/*`, but reads canonical concepts first. Famous migration records are deterministic fallback content, superseded by canonical records on slug collision.

Ask Calyx uses the server-owned conversation API and may invoke governed Brain missions for scientific turns.

`GET /api/lexicon` and `/api/lexicon/entries/{slug}` expose `definition_versions[].citation_identity` to the Famous Lexicon frontend and other Lexicon API consumers, allowing citations and exact literature evidence to be correlated without treating confidence as verification or changing review/publication state.

## Remaining release gates

- Exact-head backend CI
- Exact-head frontend test/build/lint
- Review-thread inspection
- Merge to canonical main only after green validation
- Subsequent content reconciliation/import of the 420-term working inventory and existing illustration catalogue
