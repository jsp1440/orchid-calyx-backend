# BUILD-065 — Completion Report

**Scope:** World Plants (Dr. Michael Hassler) established as the single canonical
taxonomic backbone, extending the BUILD-060…064 Knowledge Graph architecture.
Read-only. Branch `feat/scientific-knowledge-graph-completion`, PR #56.
**No merge, no publish, no production writes.**

## Parts delivered
1. **World Plants forensic audit** — one release (Hassler Feb 2026, 34,602
   records) registered twice under the same `file_sha256`; newest kept
   `canonical`, the duplicate marked `superseded`, provenance preserved. The
   pre-existing `taxonomy_identity.canonical_taxon` is POWO-derived and does not
   satisfy the owner decision.
2. **Canonical taxon registry** — 73,661 taxa (31,727 accepted, 41,934 synonyms,
   127 hybrids); synonyms resolve to accepted taxa; GBIF/POWO/IPNI/WFO/NCBI ids
   attach as 46,782 mappings, never competing taxonomies.
3. **Crosswalk consolidation** — reused BUILD-064's 10,409-pair crosswalk;
   classified all as auto-publishable accepted-name mappings; 0 fuzzy;
   fuzzy mappings are never auto-published.
4. **`Taxonomic_Conflict_Report.xlsx`** — 0 duplicate accepted taxa, 376
   unresolved synonym chains, 323 authority disagreements.
5. **Controlled activation** — `ExecutionMode.LIMITED_POPULATION` + activation
   allowlist (media, traits, pollinators, occurrences). Climate, conservation,
   mycorrhiza, literature remain DISABLED. Batched, checkpointed, idempotent,
   reversible.
6. **Validation** — AUDIT + DRY_RUN + LIMITED_POPULATION all clean: 0 invalid,
   0 orphan edges, 0 production writes.
7. **Owner safety checkpoint** — see `06-validation-and-safety-checkpoint.md`.
8. **Tests** — 25 new (89 total KG tests) pass; no production writes.
9. **Docs** — `docs/BUILD-065/00…06`.
10. **Deliverables** — module, orchestrator mode, artifacts, reports, xlsx.

## Deliverables
- `runtime/knowledge_graph/canonical_taxonomy.py` (new)
- `runtime/knowledge_graph/orchestrator.py` (LIMITED_POPULATION + activation)
- `runtime/knowledge_graph/__init__.py` (exports)
- `tests/test_canonical_taxonomy.py` (25 tests)
- `docs/crosswalks/canonical_taxon_registry.csv`
- `docs/crosswalks/build065_{audit,dry_run,limited_population}_report.json`
- `docs/BUILD-065/Taxonomic_Conflict_Report.xlsx`
- `docs/BUILD-065/{canonical_registry_summary,crosswalk_classification,conflict_detail}.json`
- `docs/BUILD-065/00…06*.md`

## Verdict rationale
Controlled activation of the four defensible domains projects cleanly (2,907
nodes / 2,907 edges, 0 invalid, 0 orphan edges) with zero production writes. The
376 unresolved synonym chains and 323 authority disagreements must be resolved by
the owner, and the four withheld domains remain disabled, before broader
(full CONTROLLED) population. The system is therefore ready for the *limited*
scope now, pending owner sign-off for anything beyond it.

READY FOR LIMITED SCIENTIFIC GRAPH POPULATION
