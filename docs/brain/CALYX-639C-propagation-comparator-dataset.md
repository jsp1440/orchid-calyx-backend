# CALYX-639C — Terrestrial Propagation Comparator Dataset

**Status:** implemented; Research Station registration-ready; rows not yet persisted  
**Parent:** CALYX-639 / CALYX-639B  
**Dataset schema:** `calyx-propagation-comparator-dataset/v1`

## Purpose

CALYX-639B established independent terrestrial-orchid evidence for vegetative-to-PLB regeneration. CALYX-639C converts that evidence into a deterministic analytical dataset while preserving source and taxon boundaries.

The comparator dataset is intentionally separate from the *Thelymitra variegata* flagship dataset. This prevents a later analysis from silently treating evidence from *Spathoglottis*, *Ipsea*, *Hemipilia* or *Anoectochilus* as if it were direct *Thelymitra* evidence.

## Implemented dataset

`runtime/propagation_comparator_dataset.py` emits nine rows across four taxa:

- *Spathoglottis plicata*
- *Ipsea malabarica*
- *Hemipilia cucullata*
- *Anoectochilus roxburghii*

Each row preserves:

- observation id;
- source id;
- taxon;
- explant and explant origin;
- treatment factors;
- response and response direction;
- quantitative value/unit when explicitly reported;
- response time when explicitly reported;
- DOI/PMID and evidence completeness;
- source and observation checksums;
- `directly_about_thelymitra = false`;
- `prediction_authority = false`;
- `publication_authority = false`.

The explicit *Ipsea* kinetin non-induction result remains a negative row. The *Anoectochilus* axillary-bud-meristem → direct PLB observation remains identifiable as the strongest meristem comparator.

## Research Station contract

Dataset id:

`dataset-terrestrial-orchid-vegetative-plb-comparators-v1`

Schema reference:

`calyx://schemas/propagation-comparator-dataset/v1`

The adapter generates:

- canonical rows SHA-256 compatible with CALYX-617 stable-row semantics;
- deterministic package SHA-256;
- a `ResearchStationService.add_dataset`-compatible registration packet;
- readiness state that refuses to claim row persistence.

Current integration state:

- registration packet ready: true;
- CALYX-617 analysis-row compatibility: implemented by contract;
- Research Station rows persisted: false;
- row transport dependency: CALYX-631;
- automatic registration: false;
- scientific publication authority: false;
- Knowledge Graph mutation authority: false.

## Validation

`tests/test_propagation_comparator_dataset.py` verifies:

- nine rows and four taxa;
- all rows remain non-*Thelymitra* evidence;
- canonical checksum matches the CALYX-617 reference algorithm;
- negative kinetin evidence survives flattening;
- direct meristem comparator evidence survives flattening;
- package and registration packet are deterministic;
- readiness does not claim row persistence or publication authority.

The CALYX-639 CI workflow now compiles the comparator dataset module and runs five focused test files. It also watches all three CALYX-639 Brain records.

## Governance

This dataset is an evidence-comparison substrate, not a propagation recommendation engine. Cross-taxon similarity can support experimental prioritization but may not be converted automatically into an inferred *Thelymitra* protocol or success probability.
