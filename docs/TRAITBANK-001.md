# TRAITBANK-001 — Operational TraitBank slice

**Contract:** `oc-traitbank-v1`. The contract is vendored from Orchid-Continuum-Brain PR #246 (commit `2f5623212b603c3026e23255b39f126a132ea69e`) and pinned by sha256.
**Classification:** `CONTINUE`. This slice continues the Brain reference implementation into the canonical backend.
**Lane:** literature/scientific data. The slice touches no other lane's files except one router registration in `app/routers/health.py`.

## What is operational in this branch

| Capability | Where | How it reuses existing systems |
|---|---|---|
| Contract pin | `contracts/traitbank_v1.json`, `app/traitbank/contract.py` | Same vendored-and-pinned pattern as `decision_fabric_v1.json`. A drifted contract, or one that grants authority, is refused. |
| Ontology terms | `contracts/brain/OAO_Term_Registry.csv` | The Brain's canonical OAO registry, vendored verbatim and pinned. Definitions referencing unknown or non-character OAO ids are refused. No ontology is created here. |
| Persistence | `migrations/20261011_oc_traitbank_v1.sql` (schema `oc_traitbank`) | Uses the existing SQL-migration convention. Tables are append-only (a trigger refuses UPDATE and DELETE). Checks mirror the contract. |
| Canonical taxa | `app/traitbank/taxa.py` | Reuses the `research_traits` resolution: same tables (`oc_taxonomy.taxa`, `public.orchid_taxonomy`), same order, same refusal of ambiguous names. `taxon_id` is the `taxonomy_id` the Matrix and KG sources already use. |
| Controlled ingestion | `app/traitbank/repository.py`, `app/traitbank/cli.py` | One transaction per batch. Guards and reference checks run first, and any violation refuses the whole batch (see the next section). |
| Literature pathway | `app/traitbank/adapters.py::from_paper_knowledge` | Consumes the existing `PaperKnowledge` model. |
| EOL TraitBank pathway | `app/traitbank/adapters.py::from_traitbank_harvester` | Consumes `TraitBankHarvester` records, parsed with the harvester's own parser. Local files only; nothing is downloaded. |
| Read-only API | `app/traitbank/routes.py` (`/api/traitbank`) | GET only, behind the same default-deny `owner_or_member_read` as `/api/research/traits`. |
| Matrix | `projection.matrix_assertions`, `GET /api/traitbank/matrix` | Produces `RelationshipAssertion` records, built with the existing `build_relationship_matrix`. Taxon-level assertions use the `trait` dimension (same `trait:{name}={value}` identity as the governed source). Lower levels use `trait_individual_evidence`. |
| Calyx | `projection.calyx_envelope`, `GET /api/traitbank/taxa/{id}/calyx/{trait}` | Returns an `oc-parallel-v1` reasoning envelope, plus `BrainCandidateHandoffRequest` previews for the existing candidate-knowledge pipeline (review REQUIRED, unpublished, no graph mutation). |

### Ingestion rules

These are what `repository.py` and `cli.py` enforce, in addition to running guards and reference checks before any write:

- **Idempotency:** `batch_key` is the idempotency key. The same payload is a no-op; a reused key with a different payload is refused.
- **Duplicates:** a source record (`source_id`, `original_record_id`, `trait_id`) is stored once. An identical resubmission is skipped; a different one is refused, never overwritten.
- **Dry-run by default:** writing needs `--apply` and `--ingested-by`.
- **Database selection:** the database comes from `TRAITBANK_DATABASE_URL` or `--database-url` only, never from a generic `DATABASE_URL`.
- **Fixture mode cannot write.**

### Query endpoints

All are GET; all are read-only.

| Need | Endpoint |
|---|---|
| Taxon | `/taxa/{taxon_id}`, `/species?name=` |
| Genus | `/genera/{genus}` |
| Character | `/characters/{trait_id}` |
| Habitat | `/habitats?term=` |
| Evidence and provenance | `/assertions/{assertion_id}`, `/sources/{source_id}` |
| Conflicts | `/conflicts?taxon_id=&trait_id=` |
| Calyx | `/taxa/{id}/calyx/{trait}` |
| Matrix | `/matrix?taxon_id=` |

### Scientific-integrity guarantees (tested)

- **Original observations are kept.** The verbatim value, unit, excerpt, locator, citation, license, contributor, observation level and scope basis are stored, and are returned by `/assertions/{id}`.
- **Conflicts are preserved.** Conflicting assertions are all stored. Conflicts are computed at read time with `resolution: preserved_not_collapsed`. The Matrix marks both sides `conflicting`, and the Calyx candidate is set to `review_required` with the contradictions listed.
- **No generalisation from individuals.** Specimen, population and observation evidence never becomes a species value. The Calyx predicate is then `has_trait_evidence_from_individuals`, and the statement says the values describe the individuals measured.
- **Missing confidence stays `NULL`.** It is never 0.5 and never 0.0.
  - The Calyx envelope reports `confidence_state: unknown` (or `partially_unknown`) and `confidence: null`.
  - Such evidence is withheld from candidate-knowledge handoff with reason `CONFIDENCE_NOT_REPORTED_NOT_DEFAULTED`, because that request model requires a number and TraitBank will not invent one.
  - Note for the owning lane: `app/parallel_platform/reasoning_contract_bridge.py` currently converts a missing Brain confidence to `0.0` (`float(candidate.get("confidence") or 0.0)`). TraitBank does not use that bridge. The behaviour is left untouched here because it belongs to another lane, and it is reported in the PR.
- **Placeholders cannot enter live storage.** Live ingestion refuses:
  - records carrying `fixture_status`;
  - `example.org`/`oc-fixture` hosts;
  - the test DOI prefix `10.5555/`;
  - `[synthetic]` markers;
  - fixture-style ids;
  - namespaced fixture taxon ids such as `taxon:1002`;
  - taxa absent from the canonical taxonomy;
  - unregistered traits.
- **Privacy.** In every mode, coordinates (decimal, labelled, degree-minute), e-mail addresses and phone numbers are refused in all free-text fields. Unknown payload keys are refused, so a locality field cannot be carried in.
- **`VERIFIED` requires reviewed provenance.** The database enforces this too.
- **Grower (`living_collection`) records** are not handed to candidate-knowledge until they are reviewed.

## Working demonstration (executed against a disposable PostgreSQL 16)

The source is Darwin (1862), which reads "nectaries eleven and a half inches long" for *Angraecum sesquipedale*. The flow is source evidence → extraction/normalization → TraitBank storage → query → Calyx/Matrix projection. The same flow runs in CI (`.github/workflows/traitbank-001-validation.yml`, step "Controlled ingestion rehearsal").

```
python -m app.traitbank.cli load-definitions --apply           # 6 definitions, OAO-validated
python -m app.traitbank.cli normalize-paper tests/fixtures/traitbank/darwin_1862_paper_knowledge.json > batch.json
python -m app.traitbank.cli ingest batch.json                  # DRY_RUN_OK
python -m app.traitbank.cli ingest batch.json --apply --ingested-by NAME   # INGESTED
python -m app.traitbank.cli ingest batch.json --apply --ingested-by NAME   # ALREADY_INGESTED
```

1. **Storage.** One specimen-level assertion is stored: 292.1 mm, with verbatim value "eleven and a half inches", excerpt "nectaries eleven and a half inches long", license public domain and evidence state `PROVISIONAL`.
2. **Calyx.** The predicate is `has_trait_evidence_from_individuals`. The statement reads "…must not be presented as typical of the species. Evidence has not been verified by a reviewer." Darwin's moth prediction appears as an "Untested adaptive hypothesis".
3. **Matrix.** The record is `trait_individual_evidence` with object id `trait:spur length=292.1 mm@specimen`, state `present`, and `graph_mutation: false`.

Confidence 0.95 here is the extraction confidence reported by the literature pipeline. Its meaning is `fidelity_to_source_not_biological_generality`.

## Not yet implemented (each needs its own reviewed step)

1. **No production data.** The migration has not been applied to any production database. No production ingestion has run, and no real EOL TraitBank extract has been loaded (no bulk download was performed).
2. **No automatic pipeline wiring.** The literature-extraction and harvester pipelines do not call TraitBank automatically. Ingestion is the operator-run CLI. A scheduled job would need owner approval and must reuse the existing harvester/orchestrator scheduling, not a new scheduler.
3. **No KG writes.** Nothing is written to `oc_graph`. KG admission stays the governed candidate-knowledge → review → materialization path. TraitBank only produces review-required candidate previews and does not call `handoff_brain_candidate` from an HTTP route.
4. **Matrix dimension not registered.** `trait_individual_evidence` is not yet registered in the governed source registry (`runtime/knowledge_graph/source_registry.py`). TraitBank Matrix output is served by `/api/traitbank/matrix` and is accepted unchanged by `/api/matrix-relationship/build`.
5. **No supersession workflow.** Correction is append-only (a new assertion). A review UI and supersession endpoint do not exist yet.
6. **Units.** Unit conversion covers length only.
7. **Breeding extension not ported.** The Brain breeding extension (ploidy, crosses, inheritance) has no backend tables in this slice.
8. **No real EOL predicate aliases.** Real EOL predicate URIs must be verified before being added as aliases in `app/traitbank/definitions_v1.json`.
9. **Species name matching.** Species-name resolution matches the canonical name column exactly, as `research_traits` does. Names stored with authorship will not match a bare binomial. That is existing canonical behaviour and is not changed here.
