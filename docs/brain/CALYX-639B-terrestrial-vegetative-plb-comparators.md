# CALYX-639B — Terrestrial Vegetative-to-PLB Comparator Evidence

**Status:** implemented; candidate/comparator evidence; scientific review required  
**Parent:** CALYX-639 / issue #639 / draft PR #640  
**Schema:** `calyx-terrestrial-orchid-propagation-comparator/v1`

## Why this slice exists

CALYX-639 identified a critical evidence gap: Davis et al. demonstrate PLB induction/re-induction in *Thelymitra variegata* from primary protocorm and PLB-derived material, but do not establish mature tuber, meristem, shoot, node, leaf or other vegetative tissue as a direct entry point.

The appropriate next question was therefore not “does generic orchid tissue culture exist?” but:

> Is vegetative-tissue-to-PLB regeneration documented in **other terrestrial orchids** strongly enough to justify the *Thelymitra* experiment as a testable hypothesis?

Two independently indexed PubMed abstracts provide direct comparator evidence.

## Comparator 1 — *Spathoglottis plicata*

Teng, Nicholson & Teng (1997), *Micropropagation of Spathoglottis plicata*, Plant Cell Reports. DOI `10.1007/s002990050329`; PMID `30727588`.

Abstract-verified evidence encoded:

- nodal and leaf explants came from 8-month-old pot-grown seedlings;
- nodal explants produced PLBs followed by plantlet development at **98.5%**;
- leaf explants did so at **6.5%**;
- some regenerated-plantlet root segments also produced PLBs;
- the reported optimum PGR combination for maximal PLB regeneration was **5.37 µM NAA + 0.44 µM BA**;
- regenerated PLBs/plantlets could regenerate further PLBs after subdivision and subculture.

This establishes direct vegetative-explant → PLB precedent in a terrestrial orchid, while also demonstrating strong explant dependence.

## Comparator 2 — *Ipsea malabarica*

Martin & Madassery (2005), *Rapid in vitro propagation of the threatened endemic orchid, Ipsea malabarica through protocorm-like bodies*, Indian Journal of Experimental Biology. PMID `16187536`.

This comparator is especially relevant because it is a threatened terrestrial orchid and the starting vegetative material was linked to field-grown rhizomes.

Abstract-verified evidence encoded:

- in vitro shoots were derived from **field-grown rhizomes**;
- axillary buds from those shoots converted to PLBs on MS + **13.3 µM BA + 2% commercial-grade sugar**;
- PLB conversion began within **25 days**;
- a mean **33.1 PLBs** developed within 50 days;
- **kinetin did not induce PLBs**, although it supported axillary-bud proliferation;
- transfer on the BA/sugar medium produced a mean **47.5 PLBs**;
- half-strength MS + **6.97 µM kinetin** converted **98% of PLBs to plantlets**;
- the authors attempted natural-habitat reintroduction of PLB-derived plants.

The explicit non-inductive kinetin treatment is preserved as first-class negative evidence.

## Implemented capability

`runtime/terrestrial_orchid_propagation_comparators.py` provides:

- source-level DOI/PMID provenance;
- terrestrial/conservation-context flags;
- individual explant/treatment/response observations;
- positive, low-frequency, and negative treatment directions;
- deterministic source and observation hashes;
- a comparative matrix;
- a governed `vegetative_plb_bridge_assessment()`.

The bridge assessment may conclude only:

`documented_in_other_terrestrial_orchids`

It is permanently prohibited from converting this into:

- direct *Thelymitra* evidence;
- a probability of success for *T. variegata*;
- an automatically selected explant or medium;
- scientific publication authority;
- Knowledge Graph mutation authority.

## Scientific interpretation

This new evidence materially improves the rationale for a future *Thelymitra* vegetative-entry experiment. Vegetative tissues can enter PLB pathways in terrestrial orchids, including rhizome-linked material in a threatened species. However, the very large difference between *Spathoglottis* nodal (98.5%) and leaf (6.5%) response also demonstrates why extrapolation is unsafe.

The correct conclusion is therefore:

> Vegetative-to-PLB regeneration has terrestrial-orchid precedent, making the *Thelymitra* question biologically plausible and experimentally testable, but explant identity, genotype, developmental state, medium and PGR response remain species-specific unknowns.

## Validation

`tests/test_terrestrial_orchid_propagation_comparators.py` asserts:

- both comparator sources are independent terrestrial-orchid evidence;
- the *Spathoglottis* 98.5% nodal response is represented without becoming *Thelymitra* evidence;
- *Ipsea* positive BA and negative kinetin outcomes coexist in the evidence model;
- source PMID provenance is retained;
- the bridge assessment explicitly returns precedent, not prediction.

The CALYX-639 focused CI workflow now compiles the comparator module and includes this test suite. Exact-head GitHub Actions execution remains an external blocker until a run actually starts and succeeds.

## Next scientific work

1. Expand the comparator search toward geophytic/tuberous terrestrial orchids, especially Orchidinae/Diurideae where available.
2. Acquire full texts for the highest-proximity comparator studies before using exact media as experimental recommendations.
3. Add explant developmental state, sterilization, genotype, seasonality/dormancy and tuber/rhizome state when evidence supports them.
4. Combine comparator rows with full Davis et al. treatment rows only after source-specific provenance remains separable.
5. Use the resulting matrix to rank **questions requiring experiment**, not to generate unsupported propagation prescriptions.
