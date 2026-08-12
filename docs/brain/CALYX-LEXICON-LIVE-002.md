# CALYX-LEXICON-LIVE-002 — Famous UI to canonical backend runtime contract

Date: 2026-08-11

## Mission

Finish the runtime connection between the migrated Famous AI Illustrated Orchid Lexicon frontend and the canonical Orchid Continuum Concept Registry without requiring the Famous-hosted application at runtime.

## Confirmed architecture

- The Famous-derived Lexicon UI is in `jsp1440/orchid-continuum-frontend` under `/lexicon/*`.
- Canonical public glossary science is served by `jsp1440/orchid-calyx-backend` under `/api/lexicon` and remains limited to ACTIVE + APPROVED Concept Registry records.
- The frontend migration seed is read-only fallback/presentation content; it is not a scientific write authority.
- Legacy Famous/Supabase scientific writes remain disabled.

## Runtime repairs

1. Added `GET /api/lexicon/entries/{slug}` for direct page-level canonical entry loading.
2. Canonical search now matches reviewed definitions as well as reviewed labels.
3. Frontend canonical/fallback merging must preserve canonical identity, reviewed definitions, review state and provenance.
4. Empty canonical presentation fields must not erase still-unmigrated Famous UI/presentation fields. Such fields are explicitly tracked as a Famous migration overlay.
5. Frontend direct entry loading falls back to canonical search during staggered deployment before using the static read-only migration fallback.

## Audit finding

Repository search confirms the Famous-derived interface migration but did not locate a separate full raw Famous export or local copies of the CloudFront image assets by obvious Famous/export/asset paths. `src/data/lexiconEntries.ts` remains a limited migration seed rather than proof of a complete source-data migration. Remote CloudFront references in the migrated frontend therefore remain a separate asset-self-hosting follow-up and are not part of canonical scientific authority.

## Governance

- No automatic concept promotion.
- No automatic publication.
- No pending/unreviewed concept exposure through the public slug route.
- No legacy Famous scientific writes.
- Missing canonical fields remain legitimate; migration overlays are presentation continuity, not canonical evidence.
