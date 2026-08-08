# CALYX-639 — Recalcitrant Orchid Propagation Intelligence

**Status:** implemented foundation; candidate-only; review required  
**Flagship taxon:** *Thelymitra variegata* (Queen of Sheba)  
**Engine:** `calyx-recalcitrant-orchid-propagation/v1`  
**Issue:** #639

## Why this build exists

The Queen of Sheba propagation result is more valuable to Orchid Continuum than a single cultivation recipe. It provides a first rigorous case for representing difficult-orchid propagation as experimental evidence that can be compared across taxa, explants, media, plant-growth regulators, environmental conditions and developmental outcomes.

The first build therefore captures the **experimental structure** while preserving the distinction between:

1. what a source actually reports;
2. what the source does not establish;
3. what Orchid Continuum may reasonably formulate as a research hypothesis.

## Source state

Davis et al. (2025), DOI `10.1007/s11240-025-03226-9`, is registered at **abstract-verified** completeness. The verified abstract reports:

- 10 µM 2,4-D caused 100% of primary protocorms to produce secondary PLBs;
- secondary PLBs converted to plantlets on half-strength MS with activated charcoal;
- greater conversion was reported under 3 µM BA + 0.1 µM 2,4-D in light and under 5 µM NAA + 5 µM BA in light;
- PLB re-induction from PLB-derived plantlets was optimized on basal medium + 10 µM 2,4-D;
- tuberisation was optimized by repeated transfer to commercial proprietary W3 medium.

Those observations are encoded as **reported evidence**, but the module deliberately marks them as not yet exactly reproducible from the verified abstract.

## Critical scientific boundary

The verified Davis et al. abstract does **not** demonstrate that a mature *T. variegata* tuber, shoot apex, or meristem can be surface-sterilized and induced directly into PLBs.

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

## Current reproduction blockers

Before attempting to reproduce the Kings Park work, the Literature Pipeline should acquire and extract the complete paper and capture at minimum:

- starting material provenance and seed/protocorm preparation;
- sterilization procedure;
- exact basal media recipes and supplements;
- activated-charcoal concentration;
- culture temperature;
- photoperiod/light intensity;
- sample sizes and replicate design;
- transfer intervals and culture duration;
- quantitative treatment outcomes and statistics;
- exact tuberisation procedure;
- W3 medium information available to the authors/research collaborators;
- deflasking/acclimatization method and survival.

Until those are resolved, the system returns `full_text_required=True`.

## Experimental policy for scarce material

A living Queen of Sheba plant or tuber must not become sacrificial method-development material merely because it is available. Vegetative initiation should first be developed on renewable, legally sourced *Thelymitra* or closely relevant material. The model records contamination, non-response and failed treatments as first-class evidence.

## Relationship to Research Station

CALYX-639 is a Research Station scientific-method slice. The protocol matrix is intended to become a registered Research Station dataset so CALYX-617 can later analyze treatment-response relationships without mixing reported measurements, missing values and Continuum-generated hypotheses.

No scientific publication, canonical Knowledge Graph mutation, taxonomy activation, destructive experiment, deployment or merge is authorized by this build.

## Next highest-value work

1. Acquire and ingest the complete Davis et al. paper.
2. Convert the full treatment tables and methods into protocol observations, including negative treatments.
3. Search cited terrestrial-orchid micropropagation literature for vegetative-explant/PLB initiation evidence.
4. Build a cross-species propagation matrix.
5. Only after evidence review, design a low-risk pilot using renewable material.
