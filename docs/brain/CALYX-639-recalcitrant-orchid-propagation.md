# CALYX-639 — Recalcitrant Orchid Propagation Intelligence

**Status:** implemented foundation + protected science API + Research Station dataset adapter; candidate-only; review required  
**Flagship taxon:** *Thelymitra variegata* (Queen of Sheba)  
**Engine:** `calyx-recalcitrant-orchid-propagation/v1`  
**Dataset schema:** `calyx-propagation-evidence-dataset/v1`  
**Issue:** #639  
**Draft PR:** #640

## Why this build exists

The Queen of Sheba propagation result is more valuable to Orchid Continuum than a single cultivation recipe. It provides a first rigorous case for representing difficult-orchid propagation as experimental evidence that can be compared across taxa, explants, media, plant-growth regulators, environmental conditions and developmental outcomes.

The build captures the **experimental structure** while preserving the distinction between:

1. what a source actually reports;
2. what the source does not establish;
3. what Orchid Continuum may reasonably formulate as a research hypothesis.

## Source state

Davis et al. (2025), DOI `10.1007/s11240-025-03226-9`, remains registered at **abstract-verified** completeness. The verified abstract reports:

- 10 µM 2,4-D caused 100% of primary protocorms to produce secondary PLBs;
- secondary PLBs converted to plantlets on half-strength MS with activated charcoal;
- greater conversion was reported under 3 µM BA + 0.1 µM 2,4-D in light and under 5 µM NAA + 5 µM BA in light;
- PLB re-induction from PLB-derived plantlets was optimized on basal medium + 10 µM 2,4-D;
- tuberisation was optimized by repeated transfer to commercial proprietary W3 medium.

Those observations are encoded as **reported evidence**, but the engine deliberately marks them as not yet exactly reproducible.

### Publisher-preview evidence acquired 2026-08-08

The Springer publisher preview surfaced through the ResearchGate publication page adds several figure-caption-level details without exposing the complete Methods section:

- a figure shows a *T. variegata* primary protocorm after **4 weeks** on a 10 µM 2,4-D treatment with early secondary-protocorm development;
- HMSAC is explicitly defined as half-strength Murashige and Skoog with **0.1% (w/v) activated charcoal**;
- the HMS/HMSAC plantlet comparison is shown after **20 weeks**;
- the two PGR plantlet treatments (5 µM NAA + 5 µM BA and 3 µM BA + 0.1 µM 2,4-D) are shown after **20 weeks of culture in light**;
- W3 is identified as commercial medium from **Western Orchid Laboratories**;
- figure captions expose statistical-comparison metadata for HMS vs HMSAC and HMSAC vs W3, but not enough underlying treatment values to reconstruct the experiments safely.

These details are now encoded separately as `publisher_preview_figure_caption` evidence records. They do not overwrite abstract-derived observations and do not upgrade the source to full-text verified. `full_text_required=True` therefore remains binding.

## Critical scientific boundary

The verified Davis et al. evidence does **not** demonstrate that a mature *T. variegata* tuber, shoot apex, or meristem can be surface-sterilized and induced directly into PLBs.

The idea:

`mature/cultivated tuber or meristem → aseptic vegetative culture → PLB → reported multiplication pathway`

is represented as `candidate_only_unvalidated`, not as reported knowledge. This distinction is permanent unless direct evidence is acquired.

## Implemented propagation engine

`runtime/recalcitrant_orchid_propagation.py` provides:

- structured source provenance and evidence-completeness state;
- treatment-level protocol observations;
- explicit starting-material and developmental-response vocabulary;
- a deterministic machine-readable protocol matrix;
- positive-result preservation without filling missing methodological detail;
- direct vs indirect evidence checks for proposed starting materials;
- a governed vegetative-entry hypothesis;
- structural evidence-proximity scoring that explicitly is **not** a biological success probability;
- readiness/blocker reporting for replication planning;
- deterministic content hashes for provenance and replay.

The existing mounted `science_router` exposes a protected Mission Control surface:

- `GET /api/science/propagation/queen-of-sheba/source`
- `GET /api/science/propagation/queen-of-sheba/matrix`
- `GET /api/science/propagation/queen-of-sheba/readiness`
- `GET /api/science/propagation/queen-of-sheba/entry-material/{material}`
- `GET /api/science/propagation/queen-of-sheba/hypotheses/vegetative-entry`

Every propagation API response remains non-publication-authoritative. Matrix responses explicitly deny canonical Knowledge Graph mutation authority.

## Research Station dataset integration

`runtime/propagation_research_dataset.py` converts the propagation evidence into a deterministic Research Station-compatible analytical package.

The adapter provides:

- six flat treatment/outcome rows, one per reported protocol observation;
- null preservation for unreported quantitative values rather than inferred numbers;
- treatment-factor maps suitable for later transformation into analysis variables;
- six separate publisher-preview evidence records with evidence level, locator and full-text status;
- a canonical row SHA-256 using the exact stable-JSON algorithm used by CALYX-617 `ResearchAnalysisWorkflowService.canonical_rows_sha256`;
- a deterministic package SHA-256;
- a `ResearchStationService.add_dataset`-compatible registration packet containing dataset id, title, checksum, schema reference and provenance;
- explicit readiness state showing that registration metadata can be prepared now while row persistence remains unavailable on the CALYX-453 dependency branch.

The generated dataset id is `dataset-thelymitra-variegata-propagation-v1` and the schema reference is `calyx://schemas/propagation-evidence-dataset/v1`.

### Dependency boundary

CALYX-453 Research Station dataset records persist dataset **metadata/checksum/provenance**, not row bytes. CALYX-631 later introduced immutable registered-dataset row transport. CALYX-639 therefore does not falsely claim its rows have been persisted inside Research Station.

Current state is intentionally:

- `registration_packet_ready = true`
- `rows_ready_for_calyx_617_analysis = true`
- `rows_persisted_in_research_station = false`
- `automatic_registration_performed = false`
- row-persistence dependency = CALYX-631 or equivalent governed row transport

This is a working integration contract without bypassing the existing dependency architecture.

## Validation state

The branch contains three focused test groups: propagation-engine deterministic tests, protected API contract tests, and Research Station dataset adapter tests.

The dataset-adapter tests assert:

- exactly six reported experimental rows are emitted;
- missing quantities remain missing;
- the row checksum exactly matches the CALYX-617 canonical checksum algorithm;
- publisher-preview evidence remains below full-text authority;
- the 0.1% w/v activated-charcoal detail is represented as preview evidence;
- dataset packaging is deterministic;
- the registration packet matches the Research Station dataset contract;
- readiness refuses to claim row persistence and names CALYX-631 as the dependency.

`.github/workflows/calyx-639-propagation.yml` compiles both propagation modules and runs all three focused test files. The workflow path filter includes the new module and tests.

**Exact-head external validation:** no GitHub Actions workflow run exists for commit `b4ef7cd0def80b4feeaa99dda74489585537644e` as observed immediately after the dataset/Brain integration. CI is therefore **not passed** and must remain an external infrastructure blocker until a run exists and succeeds.

A local repository test run was also unavailable in this environment because the GitHub CLI/private checkout is unavailable. This limitation is recorded rather than substituting an ungrounded success claim.

## Current reproduction blockers

Before attempting to reproduce the Kings Park work, the Literature Pipeline should acquire and extract the complete paper and capture at minimum:

- starting-material provenance and the route by which the primary protocorms were originally obtained;
- sterilization procedure;
- exact HMS/basal media recipes and supplements other than the resolved 0.1% activated-charcoal preview detail;
- culture temperature;
- exact photoperiod and light intensity;
- sample sizes and replicate design;
- complete transfer intervals and treatment durations beyond the preview 4-week/20-week observations;
- quantitative treatment outcomes and full statistics;
- negative and non-responsive treatments;
- exact tuberisation procedure;
- W3 composition or a documented collaboration/substitute strategy;
- deflasking/acclimatization method and survival.

Until those are resolved, the system must continue to return `full_text_required=True`.

## Experimental policy for scarce material

A living Queen of Sheba plant or tuber must not become sacrificial method-development material merely because it is available. Vegetative initiation should first be developed on renewable, legally sourced *Thelymitra* or closely relevant material. The model records contamination, non-response and failed treatments as first-class evidence.

## Relationship to Research Station and Analysis Engine

CALYX-639 is connected structurally to the Research Station contract rather than merely naming it as a future destination. The dataset package can be registered through CALYX-453 metadata semantics, and its row checksum is compatible with CALYX-617 analysis-plan validation. Immutable row transport remains delegated to CALYX-631 rather than being reimplemented here.

No scientific publication, canonical Knowledge Graph mutation, taxonomy activation, destructive experiment, production deployment or merge is authorized by this build.

## Next highest-value work

1. Acquire the complete Davis et al. paper directly from the publisher/authors or an authorized institutional copy.
2. Convert the full treatment tables and Methods into protocol observations, including negative treatments and exact denominators.
3. Search cited terrestrial-orchid micropropagation literature for direct vegetative-explant/PLB initiation evidence and add those papers as independent sources rather than extrapolating from *T. variegata*.
4. Once the CALYX-631 dependency is available in the integration chain, persist the immutable treatment rows and execute only explicitly reviewed CALYX-617 analyses.
5. Only after evidence review, design a low-risk pilot using renewable material rather than a rare Queen of Sheba plant.
