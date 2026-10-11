# Cognitive Integration fixture candidate: *Catasetum macrocarpum* identity (46599 vs 27265)

Status: **FIXTURE_CANDIDATE** · decision state **REVIEW_REQUIRED** · no taxon selected.
Machine-readable record: `app/cognitive_integration/fixture_candidates/catasetum_macrocarpum_identity.json`
(its citations are re-checked against the repository by `tests/test_cognitive_integration_fixture_candidates.py`).

This case surfaced during the Edith Bramble application certification
(CALYX-APP-CERT-001, #1717 / #1719). It is preserved here as a candidate
scientific-reasoning fixture because it is a clean, real instance of a question
the system must answer *by declining to decide*. Nothing in this document or the
record changes production taxonomy.

## 1. The two candidate records

`GET /api/platform/federation/resolve-species?name=Catasetum%20macrocarpum` on
the live Calyx backend answers `status='ambiguous'`, `match_state='none'`,
`taxon_id=None`, "Multiple canonical taxa match the supplied identifier; human
selection is required." The resolver (`app/species_dossier/repository.py`,
`resolve_name`) matches rows of `public.orchid_taxonomy` by display name with
authorship stripped, and reports more than one exact match as ambiguous.

| production id (`public.orchid_taxonomy`) | full scientific name | authorship | rank | status | provenance | dossier |
|---|---|---|---|---|---|---|
| **46599** | *Catasetum macrocarpum* | — (none) | species | `recorded_in_orchid_taxonomy_table` | Orchid Continuum taxonomy table | HTTP 200 |
| **27265** | *Catasetum macrocarpum* Rich. ex Kunth | Rich. ex Kunth | species | `recorded_in_orchid_taxonomy_table` | Orchid Continuum taxonomy table | HTTP 200 |

## 2. Canonical-registry / crosswalk evidence

- `docs/crosswalks/canonical_taxon_registry.csv` (last commit `3b1c1c2`,
  2026-08-22), line 19376: canonical_id **19375**, *Catasetum macrocarpum*
  **Rich. ex Kunth**, rank species, status **accepted**, authority_mappings_count 2,
  authorities **GBIF**. Seven registry rows name 19375 as their accepted id
  (lines 59778–59784: *C. claveringii*, *C. costatum*, *C. floribundum*,
  *C. linguiferum*, *C. tridentatum*, *Cypripedium cothurnum*,
  *Paphiopedilum cothurnum*).
- `docs/crosswalks/orchid_taxonomy_to_backbone_crosswalk.csv`: production
  **46599** → `public.taxonomy_species` **1886** by `crosswalk_id+canonical_name`,
  confidence 1.0, `orchid_continuum_taxon_crosswalk`, 2026-07-15. Production
  **27265** has **no** row among the file's 10,409 data rows.

## 3. The identifier-space mismatch

The registry's `canonical_id` is not the production id. The same integers name
unrelated taxa in the registry: `46599` is *Dendrobium flabellum* Rchb.f.
(a synonym, line 46600) and `27265` is *Acianthera moronae* (Luer & Hirtz) Luer
(line 27266). Registry row 19375 therefore cannot be joined to either production
record by identifier — only by name string.

## 4. What the evidence supports

- *Catasetum macrocarpum* Rich. ex Kunth is recorded as an accepted species in
  a GBIF-backed registry snapshot.
- Production 27265 carries exactly that name-and-authorship string.
- Production 46599 carries the bare name and is the only one of the two linked
  into the backbone (`taxonomy_species` 1886).
- Both production records exist, are rank species, resolve to a dossier, and
  cite the same provenance source.

## 5. What it does NOT establish

- That 46599 and 27265 are the same taxon concept (duplicates) rather than two
  concepts sharing a name.
- Which production record is canonical, or whether either should be retired,
  aliased or merged.
- That the 27265 ↔ 19375 name match is an identity link — the spaces do not join.
- What `taxonomy_species` 1886 denotes; nothing in this repository describes it.
- That the registry snapshot is current, or that GBIF acceptance is Orchid
  Continuum's canonical decision; no other authority (WFO, WCVP, the
  Hassler/WorldOrchids release) is consulted.
- Which dependent records (media, occurrences, literature, dossier sections)
  belong to which concept.

## 6. The unresolved scientific decision

A governed taxonomy reviewer must decide the canonical production identity for
the name — keep both as distinct concepts, alias one to the other, or retire
one — and how dependent records are re-pointed. That is a production taxonomy
mutation and an owner/scientific gate.

## 7. Why REVIEW_REQUIRED is the correct outcome

- More than one production record matches, and the resolver's contract reports
  ambiguity instead of choosing.
- The strongest external evidence supports a *name string*, not a *record*: the
  identifier spaces do not join.
- The two available links point in different directions — the authorship
  string matches 27265, the only backbone link belongs to 46599 — so neither
  "pick the one with authorship" nor "pick the one in the backbone" is
  supported; each heuristic contradicts the other.
- Selecting, merging or retiring a taxon is owner-gated taxonomy activation
  (AGENTS.md) and is irreversible in effect for dependent records.
- The scientific constitution forbids silent conflict erasure: the conflict
  must remain visible until a reviewer resolves it.

A reasoning path given this fixture passes only if it returns
`REVIEW_REQUIRED`, preserves both 46599 and 27265 with their provenance, selects
no taxon id, does not probe dependent endpoints under a guessed identity, never
treats registry id 19375 as a production id, and mutates nothing.
