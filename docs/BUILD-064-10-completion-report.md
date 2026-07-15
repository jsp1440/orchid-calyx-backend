# BUILD-064 Completion Report

Read-only engineering build on `feat/scientific-knowledge-graph-completion`
(PR #56). No merge, no publish, no production writes. Verification: 2026-07-15.

## Work completed (Parts 1–10)
1. **Taxonomic crosswalks investigated** exhaustively. Three coexisting
   backbones identified; the authoritative `oc_taxonomy.taxon_crosswalk`
   (10,070 exact-match id↔id pairs) bridges the orchid-legacy id space used by
   the name-join domains to the OC curated space. No pure-id bridge exists to the
   KG backbone (authority mismatch: orchid→GBIF, backbone→POWO), so the final
   hop stays a canonical-name equality. (Deliverable 1.)
2. **Name-join forensics** measured for pollinators, mycorrhiza, literature
   (match/orphan/collision/fan-out rates). (Deliverable 8.)
3. **Reusable crosswalk table** produced: 10,409 `orchid_taxonomy.id →
   taxonomy_species.id` pairs with method/confidence/authority/provenance/
   quality. (Deliverables 3-artifact + 7.)
4. **Climate validated**: `species_environment_profile` is an occurrence-derived
   proxy, not climate; real climate tables exist but are empty. (Deliverable 2.)
5. **Source completeness explained**: occurrences=26 (curated table sparse; bulk
   tables have ambiguous linkage), conservation=2 (authoritative tables empty).
   (Deliverable 3.)
6. **Source registry upgraded** with per-domain connection-quality metadata.
   (Deliverable 4.)
7. **AUDIT + DRY_RUN re-run** with the improved registry: 22,492 nodes / 22,827
   edges, 0 invalid, `wrote_to_production=False`. (Deliverables 5–6.)
8. **Scientific quality classification** below.
9. **Tests extended** — 9 new (64 total) covering metadata, crosswalks,
   collisions, climate classification, completeness, confidence bounds.
10. **Ten deliverable documents** written.

## Part 8 — Scientific quality classification
| Domain | Classification | Actual rows | Confidence |
| --- | --- | ---: | --- |
| media | READY | 51 | high |
| pollinators | READY WITH OPERATOR REVIEW | 23 | high |
| occurrences | READY WITH OPERATOR REVIEW | 26 | high |
| traits | READY WITH OPERATOR REVIEW | 2807 | medium |
| mycorrhiza | PARTIALLY READY | 626 | medium |
| literature | PARTIALLY READY | 29 | medium |
| conservation | PARTIALLY READY | 2 | high |
| climate | BLOCKED | 19263 | low |

Evidence: media/pollinators resolve cleanly by id/curated name; traits and
occurrences carry data but need an operator decision (coverage / source choice);
mycorrhiza and literature carry unresolved name ambiguity; conservation is data-
empty; climate is a proxy with no real climate populated.

## Validation summary
Identity integrity, duplicate edges, orphan edges, vocabulary compliance and
provenance completeness are all clean/zero. The large `orphan_nodes` figure is
backbone taxa with no domain edge yet — coverage sparsity, not a defect.

## Blocking issues remaining
- Climate has no real (non-proxy) data populated in production.
- Conservation has no authoritative data populated.
- Mycorrhiza/literature name joins carry material orphan/collision rates and no
  applicable end-to-end id crosswalk (literature has no upstream id at all).

## FINAL VERDICT

Some domains are scientifically sound and id/curated-name connected (media,
pollinators), and others are data-bearing but need an explicit operator decision
(occurrences, traits). Climate and conservation are not populatable as real
science, and two name-join domains remain ambiguous. The system can safely
populate a subset now but not the full graph.

**READY FOR LIMITED DOMAIN POPULATION**
