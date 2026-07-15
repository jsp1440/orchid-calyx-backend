# BUILD-065 — Canonical Taxonomy Architecture

Read-only engineering on `feat/scientific-knowledge-graph-completion` (PR #56).
No merge, no publish, no production writes. Verification: 2026-07-15.

## Owner decision (authoritative)
**World Plants (Dr. Michael Hassler)** is the single canonical taxonomic
backbone of the Orchid Continuum. External authorities (GBIF, POWO, IPNI, World
Flora Online, NCBI) are **not** competing taxonomies — they are recorded as
authority *mappings* attached to the canonical World Plants taxon.

## Architecture (extends BUILD-060…064, no parallel system)
A single new module, `runtime/knowledge_graph/canonical_taxonomy.py`, adds:

- **Release selection / supersession** — `WorldPlantsRelease` +
  `select_canonical_release()`: newest World Plants release (by `acquired_at`,
  tie-broken by row count) becomes `canonical`; releases sharing its
  `file_sha256` are `superseded` (duplicate registration); all others
  `historical`. Nothing is ever deleted; provenance is preserved.
- **Canonical taxon registry** — `build_canonical_registry()` builds one taxon
  per canonical (authorless) name; synonyms point at their accepted taxon; no
  taxon is duplicated.
- **Authority mappings** — GBIF/POWO/IPNI/WFO/NCBI ids attach to the canonical
  taxon as `AuthorityMapping` records with confidence + provenance.
- **Crosswalk classification** — `classify_mapping()` /`classify_crosswalk()`:
  exact-id, authority-supported synonym, accepted-name, historical, or
  manual-review. Only the first three are auto-publishable; **fuzzy mappings are
  never auto-published**.
- **Conflict detection** — `detect_conflicts()`: duplicate accepted taxa,
  unresolved synonym chains, authority disagreements.
- **Controlled activation** — `ACTIVATED_DOMAINS` / `WITHHELD_DOMAINS` and a new
  `ExecutionMode.LIMITED_POPULATION` on the existing orchestrator that runs only
  allowlisted domains into a staging graph (never production).

Everything reuses the existing repository, publisher, orchestrator, checkpoint,
source registry, validation, provenance and quality infrastructure.

## Canonical registry (built read-only from production)
| Metric | Value |
| --- | ---: |
| Canonical authority | World Plants (Dr. Michael Hassler) |
| Canonical release | `2026-02` snapshot `f8638e1d`, acquired 2026-02-26 |
| Total taxa | 73,661 |
| Accepted taxa | 31,727 |
| Synonyms | 41,934 |
| Hybrids | 127 |
| Authority mappings | 46,782 (GBIF 46,012 · POWO 770) |

The pre-existing `taxonomy_identity.canonical_taxon` table is **POWO-derived**
(`powo_snapshot_id`, `powo_number`) and therefore does **not** satisfy the owner
decision; the World Plants canonical registry produced here supersedes it as the
canonical model. No production table was modified.
