# CALYX-LEXICON-LIVE-002 — Famous UI to canonical backend runtime contract

Date: 2026-08-11

## Status

Current-main candidate. The Famous-derived Lexicon presentation is retained in the public frontend, while scientific authority remains the Orchid Continuum Concept Registry (`oc_concepts`). Backend PR #896 supersedes closed/unmerged #889 and preserves the current Matrix/Lexicon lineage.

## Runtime contract

- `GET /api/lexicon/entries/{slug}` resolves a page directly to an ACTIVE + APPROVED concept through an APPROVED label.
- Slug resolution is an exact normalized-label lookup and is independent of broad-search result limits.
- Ambiguous approved normalized labels fail closed rather than silently selecting a homonym.
- Public Lexicon search matches APPROVED labels and APPROVED definitions only.
- `GET /api/lexicon/concepts/{concept_id}` remains the canonical approved concept lookup used by Matrix concept bindings.
- Capabilities advertise the direct canonical entry route and ambiguous-slug refusal.
- Missing canonical fields remain legitimate; the backend does not invent Famous-era enrichment.

## Full Famous export recovery

The uploaded archive `orchid-lexicon-botany 2(1).zip` supplied on 2026-08-11 is the migration source of truth for the prototype presentation. Audit confirmed a 129-file Famous/Lovable-style source export containing the original lexicon UI, editor/ingestion views, demo Calyx service, validation/knowledge-graph demo data and a 45-term `src/data/lexiconEntries.ts`.

The first GitHub migration retained only 35 fallback terms. Frontend PR #144 now restores the full 45-term export inventory. Ten source-only terms recovered from the ZIP are: Form, Symmetry, Texture, Substance, Sensu lato, Sensu stricto, Pollination syndrome, Deceptive pollination, Keiki and Bark mix.

A source-derived `famousExportRecordOverrides` layer restores the exported wording and compact record relationships for all non-Resupination fallback terms, including aliases, related terminology, contrasts, identification cautions, categories and certainty notes. Representative regressions verify:

- Labellum retains the exported definition and `lip` synonym;
- Pollinium is restored to the exported Reproductive Biology category;
- Velamen retains exported Epiphyte/Rhizome relationships;
- Non-resupination retains its exported expanded definition and identification cautions while remaining draft;
- the fallback inventory contains exactly 45 unique slugs.

Resupination receives a dedicated source-backed draft enrichment restoring anatomy, morphology, developmental mechanism, functional significance, evolutionary interpretation, variation, conservation recording guidance, relationships, schematic metadata and proposed funding recognition from the complete export.

## Restored frontend presentation

Frontend PR #144 restores the richer Famous entry experience over the canonical loader without restoring the prototype backend:

- adaptive Entry Hero;
- Quick / Learn / Scientific navigation emphasis;
- source-aware primary visual selection;
- visible aliases/synonyms;
- significance, evolution and variation sections;
- complete conservation guidance rendering;
- funding/recognition display;
- Connected Knowledge rendered only from the active `LexiconEntry` record;
- Calyx page/session context bound to the active concept.

The Resupination schematic is displayed only when matching `resupination-sequence` asset metadata exists, preventing a hard-coded diagram from being paired with unrelated canonical asset title/provenance.

## Famous migration boundary

The Famous/Lovable export is migration and presentation source material, not a scientific write authority. All recovered source records are forced to explicit draft migration state with full-export provenance.

Frontend canonical/fallback merging preserves canonical identity, reviewed definitions, review state, provenance, certainty, definition history, maturity/capability state and evidence-bearing scientific fields. Famous migration content may overlay only narrow presentation-oriented fields when canonical equivalents are empty: pronunciation, category, subcategory, etymology, visual assets and funding attribution.

Famous definitions, scientific scope/evidence prose, aliases, relationships, character states, taxa, conservation guidance, literature, maturity flags, certainty state and import identity never inherit canonical review status. A canonical-collision regression proves that recovered aliases, related terminology, cautions and certainty state disappear when the same slug is supplied by an ACTIVE + APPROVED canonical concept unless the backend itself supplies those fields.

## Legacy prototype services intentionally excluded

The export contains legacy dependencies that remain migration source material only:

- Supabase/databasepad prototype writes;
- Famous CRM subscription endpoint;
- demo-only Calyx with `USE_LIVE_CALYX = false` and curated responses;
- demo `knowledgeGraph.ts` as a local presentation dataset;
- CloudFront-hosted decorative/partner imagery.

Canonical writes remain routed through Orchid Continuum governance, and Calyx uses the canonical Speak service.

## Asset provenance audit

The export contains only `public/placeholder.svg` locally. It references nine CloudFront assets plus an external NHOS logo. Source comments explicitly identify two CloudFront files as official project-supplied brand assets (Orchid Continuum and Calyx). Seven other CloudFront files are described as decorative/photographic imagery but do not carry sufficient licensing detail in the export to justify copying them into the canonical repository. The NHOS logo remains externally owned. Ambiguous third-party/decorative imagery therefore remains external pending explicit provenance rather than being silently self-hosted.

## Matrix interoperability

The current Matrix lineage stores explicit reviewed Concept Registry UUID bindings. Direct Lexicon slug access does not fuzzy-match or mutate those mappings. Matrix concept readiness and reviewed registry derivation remain separate governed workflows.

## Review disposition

All currently raised Codex findings on frontend PR #144 are resolved:

1. direct entry routes use the direct canonical loader;
2. nested empty presentation objects are treated as empty for migration-overlay purposes;
3. Famous maturity/capability flags cannot leak into canonical state;
4. Resupination hero schematic selection is bound to asset metadata;
5. aliases/synonyms remain visible in the recovered full entry view;
6. conservation records render all supported fields or an explicit pending state.

The previous backend review findings from #889 are incorporated into #896's current-main reconstruction: hyphen-safe slug identity, exact lookup independent of broad-search limits and the documented release contract. #896 additionally fails closed on ambiguous normalized approved labels. No unresolved review threads are currently present on #896.

## Governance

- public entries require ACTIVE + APPROVED concepts;
- labels and searchable definitions require APPROVED review state;
- no automatic concept promotion;
- no automatic publication;
- no legacy Famous/Supabase scientific writes;
- no taxonomy or Knowledge Graph mutation;
- no fallback content is represented as reviewed canonical evidence;
- restored visual components render fields already present on the active record and do not manufacture graph edges, conservation claims, evidence or review state.

## Validation

Dedicated `CALYX Lexicon Live 002 Validation` compiles and executes the direct-entry contract, adjacent canonical Lexicon/Matrix registry regressions, Ruff, format and diff hygiene. Private GitHub Actions incident #481 currently prevents hosted jobs from obtaining executable steps; latest frontend jobs again report `steps: null`. A local dependency-install attempt on the source export did not complete within the available execution window, so no local-build claim is made. Zero-step failures are infrastructure evidence, not a green or red product-test result. Backend #896 remains Draft and frontend #144 remains unmerged pending trusted execution.
