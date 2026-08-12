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
15. The full source export showed that the first GitHub migration had stripped most of the rich Resupination layers. A dedicated draft enrichment now restores high-value source-backed anatomy, morphology, developmental mechanism, functional significance, evolutionary interpretation, conservation recording guidance, relationship edges, schematic asset metadata, and proposed funding recognition into the single Famous fallback Resupination record. These fields remain draft migration content and are suppressed when a canonical reviewed record supplies governed scientific fields.
16. Codex review identified a visual/provenance mismatch in the restored Entry Hero. The fix now renders the hard-coded Resupination schematic only when a matching `resupination-sequence` asset exists; otherwise a canonical URL asset is shown or the interface displays an honest in-development state. Visual title/kind/provenance and displayed asset therefore derive from the same record metadata.
17. A source-derived `famousExportRecordOverrides` layer now restores the exact exported wording and compact record relationships for all non-Resupination terms, including aliases, related terminology, contrasts, identification cautions, categories and certainty notes present in the uploaded ZIP. The override is applied only to the draft fallback inventory and is never applied to canonical records.
18. Regression coverage now proves the fallback inventory contains exactly 45 unique slugs and checks representative source fidelity: Labellum retains the exported definition and `lip` synonym, Pollinium is restored to the exported Reproductive Biology category, Velamen retains its exported Epiphyte/Rhizome relationships, and Non-resupination retains its exported expanded definition and identification cautions while remaining draft.
19. A canonical-collision regression proves that richer recovered Famous aliases, related terminology, cautions and certainty state disappear when the same slug is supplied by an ACTIVE + APPROVED canonical concept unless the backend itself supplies those fields. This prevents source recovery from becoming a backdoor publication path.
20. The restored Entry Hero again displays canonical aliases/synonyms, and the conservation section now renders every supported canonical conservation field—minimum evidence, monitoring/restoration relevance, standards mappings, linked evidence, scope and certainty—or an explicit pending state rather than a blank panel.

## Full-export audit finding

The uploaded archive `orchid-lexicon-botany 2(1).zip` is a complete Famous/Lovable-style source export containing 129 files, including the original lexicon UI, admin/editor and ingestion screens, Calyx demo service, validation data, knowledge-graph demo data, and `src/data/lexiconEntries.ts` with 45 lexicon entries.

The archive also contains legacy runtime dependencies that must not become canonical authority:

- a Supabase/databasepad client and anonymous key used by the prototype;
- a Famous CRM subscription endpoint in the site chrome;
- a demo-only Calyx service with `USE_LIVE_CALYX = false` and curated responses;
- CloudFront-hosted partner imagery.

Those legacy services are migration source material only. Canonical writes remain routed through Orchid Continuum governance, and Calyx uses the canonical Speak service.

## Review disposition

All currently raised Codex review findings on frontend PR #144 are resolved:

1. direct entry routes now use the direct canonical entry loader;
2. nested empty presentation objects are treated as empty for migration-overlay purposes;
3. Famous maturity/capability flags cannot leak into canonical state;
4. the Resupination hero schematic is bound to matching asset metadata rather than slug alone;
5. synonyms remain visible in the recovered full entry view;
6. conservation records render their supported fields or an explicit pending state instead of a blank section.

Backend PR #889 also has all previously raised Codex review findings resolved: hyphen-safe slug identity, exact lookup independent of broad-search limits, and the documented `CALYX-LEXICON-LIVE-002` release identifier.

## Governance

- No automatic concept promotion.
- No automatic publication.
- No pending/unreviewed concept exposure through the public slug route.
- No legacy Famous/Supabase scientific writes.
- Missing canonical scientific fields remain legitimate and visibly incomplete.
- Migration overlays preserve presentation continuity only; they are not canonical evidence and do not confer scientific review status.
- Recovered full-export records remain `draft` fallback content until canonical review/migration occurs.
- Restored visual components render only fields already present on the active record; they do not manufacture knowledge-graph edges, conservation claims, evidence, or review state.
- Draft Famous scientific enrichment never upgrades a canonical concept's review state or fills missing governed scientific fields on an ACTIVE + APPROVED canonical record.

## Validation boundary

GitHub-hosted workflow jobs for this change were created but received no execution steps because of the repository/account Actions runner allocation condition. The latest frontend exact-head Frontend CI job again reports `steps: null`. This is an infrastructure block, not an executed test failure. A local dependency install attempt also did not complete within the available execution window, so no local build claim is made. No green-CI claim is made, and merge remains blocked pending trusted execution.
