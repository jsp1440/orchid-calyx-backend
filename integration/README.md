# Scientific Convergence — Integration Record (Release Candidate)

Additive integration layer proving that the existing Orchid Continuum
scientific modules work together as one reproducible workflow. Nothing here
modifies existing modules, mutates the database or knowledge graph, calls a
paid provider, or downloads scientific data in bulk.

## Contents

| Path | Purpose |
|---|---|
| `integration/taxon_identifiers.py` | Cross-surface identifier classification/validation and name-bound correlation (Priority 4). |
| `integration/contracts/atlas_module_capabilities_v1.json` | Byte-verified vendored copy of the Atlas #1802 `oc.atlas-module-capabilities.v1` contract (upstream blob `cc5dbffd15c4efe5b6e9ef3efb0803a4512b77fa` @ head `0b2a3b47`) so the identifier suite is self-contained. |
| `integration/demos/morphology_pathway_demo.py` | End-to-end cross-repo demonstration (Priority 2). |
| `integration/tests/test_scientific_convergence.py` | Cross-module convergence tests (Priorities 1–2). |
| `integration/tests/test_featured_genus_contract_compat.py` | Calyx #1803 ↔ Frontend #914 contract compatibility (Priority 3). |
| `integration/tests/test_taxon_identifier_compatibility.py` | Identifier/evidence-reference compatibility (Priority 4). |

## Exact PR dependencies

| PR | Repo | Role | Head @ verification |
|---|---|---|---|
| #1793 | orchid-calyx-backend | Matrix registry foundation (base of chain) | `2e40a72a` |
| #1794 | orchid-calyx-backend | Matrix session workflow | `8b96c575` |
| #1796 | orchid-calyx-backend | Matrix identification workflow (chain tip) | `2e24b7dc` |
| #233 | Orchid-Continuum-Brain | OAO–Lexicon–Matrix–KG bridge | `2584b523` |
| #1803 | orchid-calyx-backend | Featured Genus profile/selection | `4b8e32a6` |
| #914 | orchid-continuum-frontend | Featured Genus read model | `df9f81a2` |
| #1801 | orchid-calyx-backend | Image Intelligence | `938cc47f` |
| #1802 | orchid-calyx-backend | Atlas occurrence explorer | `0b2a3b47` |

This PR branches off the Matrix chain tip (#1796 head). It does **not**
modify #1801/#1802/#1803 or any Claude-owned autonomy branch; cross-PR
verification runs against byte-verified checkouts of those heads supplied via
environment roots.

## Test environment

Provider-free, network-free, database-free. Verified with pytest 9.1.1,
sqlalchemy 2.1.4, fastapi 0.116.1, psycopg 3.3.6.

```bash
export OC_CALYX_ROOT=/path/to/orchid-calyx-backend        # this branch
export OC_BRAIN_ROOT=/path/to/Orchid-Continuum-Brain      # #233 head (optional)
export OC_FEATURED_GENUS_ROOT=/path/to/calyx-1803-tree    # #1803 head (optional)
export OC_IMAGE_INTEL_ROOT=/path/to/calyx-1801-tree       # #1801 head (optional)
python3 -m pytest integration/tests/ -q -p no:cacheprovider
```

Tests depending on an absent root skip gracefully; the pure-Calyx and
self-contained suites always run.

## Passing tests (verified 2026-10-11, run records in the mission verifier)

- Matrix chain suites (upstream #1793/#1794/#1796 tests): **101 passed**
- `integration/tests/` combined: **34 passed**
  - scientific convergence: 8 (incl. KG refusal gates, exact-only taxon
    resolution, registry roundtrip, non-UUID concept rejection; Brain-side
    contract validation, canonical OAO concept-UUID binding, conflict
    preservation)
  - Featured Genus contract compatibility: 7 (payload acceptance, degraded
    states, invalid-genus verdict, off-contract rejection, rotation/window
    equivalence at 5 epochs, boundary-validator agreement)
  - identifier compatibility: 19 (scheme classification, Atlas↔Featured
    Genus backbone agreement against the vendored declared contract, real
    #1801 id pass-through/minting/exact-lookup behavior, real Matrix
    resolver ids, Brain fixture ids, name-bound correlation discipline)
- #1803's own suites against its head: **19 passed**

## Working scientific journeys (reproducible, exit 0)

1. `scripts/matrix_identification_workflow_demo.py` — Matrix identification
   end-to-end with human-review gate, synonym ambiguity, image permissions,
   character-state uncertainty; `identification_demo_ok=True`.
2. `scripts/matrix_contributor_api_demo.py` / `matrix_contributor_intake_demo.py`
   — contributor intake with license enforcement and unverified-evidence
   labeling; `demo_ok=True`.
3. `integration/demos/morphology_pathway_demo.py` (requires `OC_BRAIN_ROOT`)
   — botanical description → anatomical concept → OAO character/state →
   taxonomic context → Lexicon reference → Matrix evidence → KG-compatible
   output; concept ids bound to canonical OAO Term Registry UUIDs; conflicts
   `preserved_not_collapsed`; **12/12 checks**,
   `morphology_pathway_demo_ok=True`.

## Remaining blockers (owner actions, unchanged by this PR)

- Matrix production binding of the taxon resolver to World Plants canonical
  data (protocol is in place; demos/tests use the static reviewable entry set).
- Featured Genus, Atlas occurrence routes and the KG loader require
  `DATABASE_URL` (+ `ATLAS_OCCURRENCE_RELATION` for Atlas) against the real
  backbone; all degrade honestly when unconfigured.
- Atlas projection decisions A–C in `docs/atlas-explorer/APPLY-ATLAS-PROJECTION.md`
  (owner-applied materialized view).
- Image Intelligence: owner-approved persistence migration for reference
  records; embedding model choice; expert-verified held-out specimens.
- Brain #233 remains draft; KG publication stays human-gated by contract.

## Required merge order

1. Brain #233 (bridge) — independent.
2. Calyx #1793 → #1794 → #1796 (Matrix chain, in order).
3. **This convergence PR** (base = #1796 head; retarget to `main` after the
   chain lands).
4. Calyx #1803 (Featured Genus) and Frontend #914 — compatible as verified
   here; merge together.
5. Calyx #1801, #1802 — independent; identifier compatibility verified here.
6. Frontend #913 last (Atlas consumer), per the existing convergence record.

## Deployment prerequisites

- No new runtime dependencies, migrations, providers or schedulers.
- `integration/` is import-only; nothing mounts routes or mutates state.
- To exercise cross-PR suites in CI, provision the three optional checkouts
  above; otherwise they skip by design.
