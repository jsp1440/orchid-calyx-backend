# CALYX-LEXICON-LIVE-002 — Famous UI to canonical backend runtime contract

Date: 2026-08-11

## Mission

Finish the runtime connection between the migrated Famous AI Illustrated Orchid Lexicon frontend and the canonical Orchid Continuum Concept Registry without requiring the Famous-hosted application at runtime.

## Confirmed architecture

- The Famous-derived Lexicon UI is in `jsp1440/orchid-continuum-frontend` under `/lexicon/*`.
- Canonical public glossary science is served by `jsp1440/orchid-calyx-backend` under `/api/lexicon` and remains limited to ACTIVE + APPROVED Concept Registry records.
- The Famous migration content is read-only fallback/presentation content; it is not a scientific write authority.
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
10. The complete Famous source ZIP supplied on 2026-08-11 established a 45-term exported lexicon inventory. The previous GitHub fallback contained 35 terms. Ten recovered terms were added as provenance-marked draft migration records: Form, Symmetry, Texture, Substance, Sensu lato, Sensu stricto, Pollination syndrome, Deceptive pollination, Keiki, and Bark mix.
11. The integrated entry page restores read-only rich sections represented in the full export—significance, evolutionary interpretation, variation, conservation guidance, and funding/recognition—without restoring the legacy demo write path.
12. The Famous adaptive Entry Hero has been restored over the canonical record loader. It provides record-driven summary cards plus Quick / Learn / Scientific depth controls. The depth controls change navigation emphasis only; they do not alter, hide, publish, or synthesize scientific record content.
13. A Connected Knowledge panel has been restored using only the active `LexiconEntry` record: broader/narrower concepts, related terminology, explicit relationship edges, example taxa, and identification character states. The separate demo `knowledgeGraph.ts` dataset remains excluded from canonical authority.
14. Calyx page/session context remains attached to the active lexicon concept, so the restored visual experience and the canonical conversational workspace share the same current-object identity.

## Full-export audit finding

The uploaded archive `orchid-lexicon-botany 2(1).zip` is a complete Famous/Lovable-style source export containing 129 files, including the original lexicon UI, admin/editor and ingestion screens, Calyx demo service, validation data, knowledge-graph demo data, and `src/data/lexiconEntries.ts` with 45 lexicon entries.

The archive also contains legacy runtime dependencies that must not become canonical authority:

- a Supabase/databasepad client and anonymous key used by the prototype;
- a Famous CRM subscription endpoint in the site chrome;
- a demo-only Calyx service with `USE_LIVE_CALYX = false` and curated responses;
- CloudFront-hosted partner imagery.

Those legacy services are migration source material only. Canonical writes remain routed through Orchid Continuum governance, and Calyx uses the canonical Speak service.

## Governance

- No automatic concept promotion.
- No automatic publication.
- No pending/unreviewed concept exposure through the public slug route.
- No legacy Famous/Supabase scientific writes.
- Missing canonical scientific fields remain legitimate and visibly incomplete.
- Migration overlays preserve presentation continuity only; they are not canonical evidence and do not confer scientific review status.
- Recovered full-export records remain `draft` fallback content until canonical review/migration occurs.
- Restored visual components render only fields already present on the active record; they do not manufacture knowledge-graph edges, conservation claims, evidence, or review state.

## Validation boundary

GitHub-hosted workflow jobs for this change were created but received no execution steps because of the repository/account Actions runner allocation condition. This is an infrastructure block, not an executed test failure. No green-CI claim is made, and merge remains blocked pending trusted execution.
