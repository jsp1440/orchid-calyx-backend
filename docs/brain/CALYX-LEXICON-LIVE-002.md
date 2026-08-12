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
2. Direct slug lookup performs an exact normalized-label query against ACTIVE + APPROVED concepts and APPROVED labels, independent of broad-search limits.
3. Canonical search now matches reviewed definitions as well as reviewed labels.
4. Frontend entry routes use the direct canonical slug endpoint instead of loading the full registry first.
5. Frontend canonical/fallback merging preserves canonical identity, reviewed definitions, review state, provenance, certainty, definition history, maturity/capability state, and evidence-bearing scientific fields.
6. Famous migration content may overlay only narrow presentation-oriented fields when canonical equivalents are empty: pronunciation, category, subcategory, etymology, visual assets, and funding attribution.
7. Every preserved Famous presentation field is explicitly named in `migration_overlay.fields`.
8. Famous definitions, scope/evidence prose, relationships, character states, taxa, conservation guidance, literature, maturity flags, certainty state, and import identity never inherit canonical review status.
9. Frontend direct entry loading falls back to canonical search during staggered deployment before using the static read-only migration fallback.

## Audit finding

Repository search confirms the Famous-derived interface migration but did not locate a separate full raw Famous export or local copies of the CloudFront image assets by obvious Famous/export/asset paths. `src/data/lexiconEntries.ts` remains a limited migration seed rather than proof of a complete source-data migration. Remote CloudFront references in the migrated frontend therefore remain a separate asset-self-hosting follow-up and are not part of canonical scientific authority.

## Governance

- No automatic concept promotion.
- No automatic publication.
- No pending/unreviewed concept exposure through the public slug route.
- No legacy Famous scientific writes.
- Missing canonical scientific fields remain legitimate and visibly incomplete.
- Migration overlays preserve presentation continuity only; they are not canonical evidence and do not confer scientific review status.

## Validation boundary

GitHub-hosted workflow jobs for this change were created but received no execution steps because of the repository/account Actions runner allocation condition. This is an infrastructure block, not an executed test failure. No green-CI claim is made, and merge remains blocked pending trusted execution.
