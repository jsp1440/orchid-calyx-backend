# CALYX-639 — Recalcitrant Orchid Propagation Intelligence

**Status:** implemented foundation + protected science API; candidate-only; review required  
**Flagship taxon:** *Thelymitra variegata* (Queen of Sheba)  
**Engine:** `calyx-recalcitrant-orchid-propagation/v1`  
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

These are preserved as **publisher-preview / figure-caption evidence**, not as a full-text verification upgrade. The engine's `full_text_required=True` state therefore remains correct.

## Critical scientific boundary

The verified Davis et al. evidence does **not** demonstrate that a mature *T. variegata* tuber, shoot apex, or meristem can be surface-sterilized and induced directly into PLBs.

The idea:

`mature/cultivated tuber or meristem → aseptic vegetative culture → PLB → reported multiplication pathway`

is therefore represented as `candidate_only_unvalidated`, not as reported knowledge.

This distinction is permanent unless direct evidence is acquired.

## Implemented capabilities

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

The existing mounted `science_router` now exposes a protected Mission Control surface without creating a second scientific store:

- `GET /api/science/propagation/queen-of-sheba/source`
- `GET /api/science/propagation/queen-of-sheba/matrix`
- `GET /api/science/propagation/queen-of-sheba/readiness`
- `GET /api/science/propagation/queen-of-sheba/entry-material/{material}`
- `GET /api/science/propagation/queen-of-sheba/hypotheses/vegetative-entry`

Every propagation API response remains non-publication-authoritative. Matrix responses also explicitly deny canonical Knowledge Graph mutation authority.

## Validation state

The branch contains the original deterministic engine tests plus focused API contract tests that assert:

- the five propagation routes are mounted;
- the DOI/source completeness state is preserved;
- the six-row matrix remains candidate-only;
- primary-protocorm evidence is distinguished from meristem hypothesis;
- unknown material fails closed;
- the vegetative-entry idea cannot be represented as Davis-reported evidence;
- full-text and unsupported-meristem blockers remain visible.

A dedicated `.github/workflows/calyx-639-propagation.yml` workflow compiles the propagation/runtime router modules and runs both focused test files. As of this Brain update, GitHub has **not started a workflow run for the exact branch head**; CI must therefore not be represented as passed. This is an infrastructure/runner validation blocker, not evidence of a successful run.

## Current reproduction blockers

Before attempting to reproduce the Kings Park work, the Literature Pipeline should acquire and extract the complete paper and capture at minimum:

- starting-material provenance and the route by which the primary protocorms were originally obtained;
- sterilization procedure;
- exact HMS/basal media recipes and supplements other than the now-resolved 0.1% activated-charcoal figure-caption detail;
- culture temperature;
- exact photoperiod and light intensity;
- sample sizes and replicate design;
- complete transfer intervals and treatment durations beyond the figure-caption 4-week/20-week observations;
- quantitative treatment outcomes and full statistics;
- exact tuberisation procedure;
- W3 composition or a documented collaboration/substitute strategy despite the now-resolved Western Orchid Laboratories attribution;
- deflasking/acclimatization method and survival.

Until those are resolved, the system must continue to return `full_text_required=True`.

## Experimental policy for scarce material

A living Queen of Sheba plant or tuber must not become sacrificial method-development material merely because it is available. Vegetative initiation should first be developed on renewable, legally sourced *Thelymitra* or closely relevant material. The model records contamination, non-response and failed treatments as first-class evidence.

## Relationship to Research Station

CALYX-639 is a Research Station scientific-method slice. The protocol matrix is intended to become a registered Research Station dataset so CALYX-617 can later analyze treatment-response relationships without mixing reported measurements, missing values and Continuum-generated hypotheses.

No scientific publication, canonical Knowledge Graph mutation, taxonomy activation, destructive experiment, deployment or merge is authorized by this build.

## Next highest-value work

1. Acquire the complete Davis et al. paper directly from the publisher/authors or an authorized institutional copy.
2. Convert the full treatment tables and Methods into protocol observations, including negative treatments and exact denominators.
3. Search the paper's cited terrestrial-orchid micropropagation literature for vegetative-explant/PLB initiation evidence.
4. Register the resulting cross-species propagation matrix as a Research Station dataset for governed CALYX-617 analysis.
5. Only after evidence review, design a low-risk pilot using renewable material rather than a rare Queen of Sheba plant.
