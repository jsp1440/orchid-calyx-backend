# IMAGE-INTEL-001 — Image intelligence, reference images and Matrix image identification

Classification: **CONVERGE**. It extends the canonical Matrix engine
(`runtime/matrix_identification.py`), the licensed-image allowlist
(`runtime/image_staging.py`), the relationship-link type
(`runtime/relationship_integration.py`), and the Vision AI evidence bundle
(`oc-vision-evidence/v1`, Brain PR #235). It does not add a parallel
knowledge graph, scheduler, taxonomy or vision engine.

Brain capability contract: `contracts/image_intelligence_v1.json` in
`jsp1440/Orchid-Continuum-Brain`.

## Modules

| Module | Role |
|---|---|
| `runtime/reference_images.py` | Reference-image record (`oc-reference-image/v1`), source normalisation for GBIF, iNaturalist, iDigBio and herbaria, expert verification, taxonomic revision, duplicate grouping |
| `runtime/image_inventory.py` | Coverage and gap analysis by accepted species and genus (about 30k species, in memory); bounded read-only inventory of the existing image tables |
| `runtime/image_characters.py` | Image character observations (observed, inferred, not visible, cannot determine); Vision-bundle adapter; description and key states with citations and conflicts; Lexicon term normalisation |
| `runtime/reference_identification.py` | Identification workflow: retrieval over verified references, Matrix character comparison, genus and species hypotheses, requests for more evidence, open-set abstention, optional calibration |
| `runtime/image_training_partitions.py` | Versioned dataset manifest: expert-verified labels only, splits grouped by specimen and duplicate group, open-set held-out taxa, leakage verification, genus and species evaluation, ECE |
| `runtime/image_evidence_graph.py` | `RelationshipLink` candidates: `depicts`, `shows_character`, `identification_hypothesis` |
| `app/routers/image_intelligence.py` | Owner-gated API at `/api/image-intelligence/*` (mounted through `reference_docs`) |

## API

- `GET /contract`: the contract version, vocabularies, rules and governance flags.
- `GET /inventory`: a read-only aggregate probe of `public.orchid_images`, `public.images`,
  `oc_core.media_assets` and `oc_vision.reference_image_set_items`. It runs inside a `READ ONLY`
  transaction, uses only `information_schema` and `GROUP BY`, and downloads nothing.
  A missing table is reported as `unavailable`, never as zero.
- `POST /coverage`: species and genus coverage, plus a prioritised gap list.
- `POST /references/validate`: validation, duplicate groups, training-label eligibility and `depicts` links.
- `POST /references/verify`: applies one expert verification event and returns the new
  record version. Nothing is persisted.
- `POST /identify`: evidence-linked hypotheses with agreements, contradictions, citations,
  reference images, evidence requests and governance flags.
- `POST /datasets/manifest` and `POST /datasets/evaluate`: build a leakage-safe manifest,
  then evaluate supplied predictions.

## Scientific rules enforced in code and tests

1. Accepted taxonomy (authority and version) and specimen identification verification are separate fields.
2. Source identifications are never ground truth. iNaturalist research grade counts only as `community_consensus`.
3. Only `expert_verified` images with an allowed license, an accepted taxon and a taxonomy version are training labels.
4. Synonymy keeps the specimen verification. A split clears the placement and sets `needs_reverification`.
5. A character that is not visible or cannot be determined never contradicts a description and creates no graph edge.
6. Absolute measurements without calibration are withheld (`UNCALIBRATED_ABSOLUTE_MEASUREMENT_WITHHELD`).
7. Conflicting descriptions are kept with every citation and marked `uncertain`.
8. Visual similarity alone is capped and never yields a species or genus decision.
9. An explicit "unrepresented taxon" alternative absorbs probability, and the workflow flags possible out-of-distribution taxa.
10. Probabilities are labelled uncalibrated unless a calibration table from a held-out evaluation is supplied.
11. Identification outputs are provisional, non-authoritative and never training labels.
12. Every image of a specimen, occurrence or duplicate group stays in one split. `verify_no_leakage` re-checks this independently.

## Validation

`tests/test_image_intelligence.py` uses synthetic fixtures only. CI: `.github/workflows/image-intelligence-001.yml`.

## Not done here (owner-governed or blocked)

- No model was trained, and no performance on real data is claimed.
  The evaluation pipeline is exercised on synthetic fixtures only.
- The production inventory has not been run. `GET /inventory` needs a deployed database
  and owner execution.
- Reference records are not persisted yet. The `oc_vision.reference_image_set_items`
  migration exists but is not auto-applied. A durable store needs an approved, additive migration.
- There is no iDigBio or herbarium harvester in Calyx. The normaliser accepts iDigBio
  rows once a bounded harvester exists.
- The image-embedding model has not been selected. Embeddings are inputs to this API.
  No paid inference is used.
