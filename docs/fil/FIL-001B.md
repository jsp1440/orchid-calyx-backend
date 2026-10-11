# FIL-001B — One capability view, taxon-resolution contracts, and an offline Literature → Calyx chain

Status: **non-production prototype, draft PR stacked on FIL-001A (#1808).**
FIL-001B adds no scheduler, queue, lease, spending ledger, taxonomy spine, registry of record or autonomy framework. It enables no unattended execution.

## Reconciliation with concurrent work (done before implementation)

| Concurrent work | What it owns | How FIL-001B stays compatible |
|---|---|---|
| Brain #246 TraitBank (`oc-traitbank-v1`, head `2f56232`) | Trait definitions anchored to OAO; assertion levels; TraitBank ingest of the backend harvester record shape and `PaperKnowledge`; Calyx/Matrix projections | FIL emits records in the harvester shape (`harvesters.traitbank` `_normalize`, checked by `_validate_traitbank_record`). It uses #246's `raw.record_id`, `resource_id`, `citation`, `license` and `fixture_status` keys. It resolves taxa against the same `canonical_taxonomy` spine. FIL does not define traits; that stays in #246's registry. See the cross-check below. |
| Brain #247 LIT-EVIDENCE-001 (stacked on #230/#232/#236/#234/#233) | Brain-side literature → evidence slice: character-aware extraction, OAO mapping, spine reconciliation, hash-chained staging ledger | Not imported, since it is unmerged and stacked. FIL uses the backend's canonical `app.literature_extraction` pipeline. The two meet at shared contracts: `oc-verification-handoff-v1` / `oc-parallel-v1` envelopes and TraitBank candidate rows. FIL adds no second Brain-side extractor or ledger. |
| Backend `app.literature_extraction` | Canonical literature pipeline (`PaperKnowledge`) | Run in-process, unchanged, with no output writer. Claims keep exact character spans and the document's sha256. |
| Canonical taxonomy (`runtime/knowledge_graph/canonical_taxonomy.py`, World Plants) | The single taxonomy spine | Used read-only with exact matches only. No taxa are created and nothing is matched fuzzily. |
| Brain–Calyx autonomy PRs (backend #1795, #1806, #1790; Brain #244, #239, #224) | Scheduler, timer cycles, governed Brain verification admission, verification-packet production | FIL admits candidates only through the existing `reasoning_contract_bridge.verification_packet_to_handoff_request` and `handoff_brain_candidate`. It declares plans to the existing router (`route_task`) and claims nothing. |
| Backend `app.candidate_knowledge` and its PostgreSQL snapshot store | Durable, idempotent candidate persistence | Used as the durable evidence store. No new table or store is added. |

## What FIL-001B adds

1. **One canonical capability view** (`app/functional_interaction/capability_view.py`, `oc.fil.canonical-capability-view.v1`).
   - `provider_reservoir.CAPABILITIES` is the canonical list.
   - Executor roles, `ExecutorCapability` and the Brain capability ids join it through explicit crosswalks.
   - These all raise:
     - an unmapped vocabulary member;
     - a stale crosswalk entry;
     - a mapping to an unknown canonical name;
     - a FIL descriptor whose Brain link disagrees with the crosswalk.
   - Coverage is reported, not asserted. Executor roles map to 0/4 and Brain capabilities to 2/6; the others are recorded with reasons.
   - Mirror drift that cannot be read from here is recorded as data (`firecrawl-acquisition`).
2. **Taxon-resolution requirements as a contract** (`TaxonResolutionPolicy`, an optional, additive descriptor field).
   - **Providers** must name the authority, use only `accepted|synonym|unresolved|ambiguous`, and exclude fuzzy matching.
   - **Requirers** (TraitBank, Calyx) admit only `accepted|synonym`.
   - Declared conditions make planning fail when no provider sits upstream.
   - The dry run checks every emitted taxon link at runtime: `TAXON_RESOLUTION_VIOLATION:*`.
3. **Offline end-to-end chain** (`app/functional_interaction/literature_to_calyx.py`), planned, governed and dry-run through FIL:
   - **Literature.** The canonical pipeline produces 13 span-anchored claims from 3 synthetic papers.
   - **Taxonomy.** Names are matched exactly against World Plants: 4 accepted, 2 via synonym, 1 ambiguous and 6 unresolved (5 of those name no taxon at all).
   - **Evidence.** `extract_candidates` structures the claims. Hedged and interpretation claims carry uncertainty markers. Nothing is ever `VERIFIED`.
   - **TraitBank.** 6 harvester-shaped records plus `CandidateInput`s. The existing aggregation service accepts them.
   - **Calyx.** 6 `oc-verification-handoff-v1` packets go through the existing bridge into candidate knowledge, all `review_state=REQUIRED` and `published=False`.
4. **Work-claiming compatibility** (`work_declaration.py`).
   - A plan is rendered as `OC-SWARM-CAPABILITY` markers and classified by the existing router.
   - Result: provider-free, `lane_executable=False` ("building it needs open-ended-code-authoring").
   - No issue, label, lease or schedule is created.

## Scientific behaviour (asserted by tests)

- **Provenance.**
  - Every claim's `statement` equals `text[char_start:char_end]` of its source.
  - Provenance strings carry the DOI, `sha256:<document hash>` and the character span.
  - Persisted Calyx evidence links keep them.
- **Contradiction.**
  - *Fixtureia beta* (a synonym) "flowers in winter" and *Fixtureia alpha* "flowers in summer" become two `CONTRADICTORY` candidates that name each other. Their `review_state` is `review_required` and the pathway is `resolve_conflicting_sources`.
  - Aggregation independently reports `MULTIPLE_VALUES`.
- **Variation is not conflict.** 12 mm vs 15 mm at an unstated assertion level is recorded as `VARIATION_AT_UNSTATED_LEVEL` with knowledge gap `assertion_level_unstated`. This matches #246's rule that differences between specimens are variation.
- **Uncertainty.**
  - "may be pollinated by…" keeps `HEDGED_SOURCE_LANGUAGE` and `INTERPRETATION_NOT_OBSERVATION`.
  - Its pathway is `expert_review_of_uncertain_claim`.
  - Single-source candidates list `independent_corroboration` as missing evidence.
- **Withheld, never dropped.** Unresolved, ambiguous and unstructured claims travel to Calyx as recorded gaps with their provenance.

## Durable scientific evidence

`tests/test_fil_001b_durable_evidence.py` (`requires_postgres`) runs the chain against the existing `PostgresCandidateRepository` on a **disposable test database**. It checks that:

- candidates persist;
- a fresh repository instance reloads them with their review gates, contradiction lists and source anchors;
- an identical replay reuses every candidate (same ids, no new rows);
- the advisory lock is released.

In CI it runs against the workflow's Postgres service. An unusable database fails the run rather than skipping it (`tests/conftest.py`).

## TraitBank #246 cross-check (executed locally; not a CI test, because #246 is unmerged Brain code)

The 6 FIL records were fed to #246's `ingest_traitbank_records` with #246's own trait registry, using a read-only checkout of #246's head `2f56232`.

- **Shape.** All 6 were accepted by the ingest without error.
- **Taxonomy.** #246's `CanonicalSpineResolver`, given the same backbone records, resolved *Fixtureia alpha* → `taxon:1` and *Fixtureia delta* → `taxon:2`, exactly as FIL did.
- **Traits.** All 6 were held as `unmapped: trait_not_registered`. `extract_candidates` emits generic predicates (`phenology`, `measurement`, `has_trait`) and drops the character: "spur length was 12 mm" becomes `measurement`. Mapping to OAO-anchored ids such as `oc:trait:spur_length` needs character-aware extraction (#247 / KO-0066). That is a recorded blocker, not something FIL should duplicate.

## Validation (local)

- `pytest tests/test_fil_001*.py`: **87 passed** (57 FIL-001A + 30 FIL-001B). This includes the Postgres durability test against a disposable local PostgreSQL 16, and was re-run in a clean venv built from `requirements-scientific.txt` and `requirements-dev.txt` with `CI=true`.
- **Regression suites for reused code: 153 passed.** These were critical-suite coverage, source compiles, the reasoning bridge, candidate handoff, the literature pipeline, the provider reservoir, the Brain capability registry and canonical taxonomy.
- **Mutation sweep: 13 of 13 FIL-001B guard mutants killed.** The sweep ran with bytecode caching off, an unmutated control was green before and after, and the sources were restored byte for byte. The guards covered:
  - crosswalk unmapped, stale and disagreeing entries;
  - the fuzzy, authority and admission taxon checks;
  - the policy's fuzzy and condition invariants;
  - ambiguity;
  - contradiction vs variation;
  - hedging;
  - withholding;
  - missing corroboration.
- `ruff check` / `ruff format --check` (0.16.8), `compileall`: clean.

## Remaining blockers

1. **Trait mapping.** Generic candidate predicates cannot be mapped to TraitBank trait ids. This needs character-aware extraction (#247 / KO-0066) and #246's registry to land.
2. **Taxon recognition in literature.** The backend `EntityExtractor` recognises only a fixed list of taxa (e.g. *E. coli*, *Arabidopsis*, *Odontoglossum*). FIL compensates with exact backbone and declared-keyword matching. Fixing the extractor belongs to the literature lane.
3. **Bridge granularity.** The existing bridge stores provenance items as anchor `logical_unit` strings and drops numeric character spans. FIL keeps the span inside the string; a structured anchor is the bridge owner's change.
4. **Capability vocabulary.**
   - Four Brain capabilities and all four executor roles have no canonical capability name.
   - `firecrawl-acquisition` is absent from the Brain and frontend mirrors.
   - Naming them is a governance and capability-registry decision.
5. **Packet producer.** The canonical `oc-verification-handoff-v1` producer is Brain-side (#224 / #239, unmerged). FIL's packets are labelled `producer: fil-001b-offline-fixture-chain`.
6. **Owner-gated items.** Any production persistence, real-literature ingestion, taxonomy activation or unattended lane execution remains owner-gated. None is enabled here.
