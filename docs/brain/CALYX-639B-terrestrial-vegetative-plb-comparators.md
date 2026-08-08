# CALYX-639B — Terrestrial Vegetative-to-PLB Comparator Evidence

**Status:** implemented; candidate/comparator evidence; scientific review required  
**Parent:** CALYX-639 / issue #639 / draft PR #640  
**Schema:** `calyx-terrestrial-orchid-propagation-comparator/v1`

## Why this slice exists

CALYX-639 identified a critical evidence gap: Davis et al. demonstrate PLB induction/re-induction in *Thelymitra variegata* from primary protocorm and PLB-derived material, but do not establish mature tuber, meristem, shoot, node, leaf or other vegetative tissue as a direct entry point.

The appropriate next question was therefore not “does generic orchid tissue culture exist?” but:

> Is vegetative-tissue-to-PLB regeneration documented in **other terrestrial orchids** strongly enough to justify the *Thelymitra* experiment as a testable hypothesis?

Four independent primary-source records now provide direct comparator evidence.

## Comparator 1 — *Spathoglottis plicata*

Teng, Nicholson & Teng (1997), *Micropropagation of Spathoglottis plicata*, Plant Cell Reports. DOI `10.1007/s002990050329`; PMID `30727588`.

Abstract-verified evidence encoded:

- nodal and leaf explants came from 8-month-old pot-grown seedlings;
- nodal explants produced PLBs followed by plantlet development at **98.5%**;
- leaf explants did so at **6.5%**;
- some regenerated-plantlet root segments also produced PLBs;
- the reported optimum PGR combination for maximal PLB regeneration was **5.37 µM NAA + 0.44 µM BA**.

This establishes direct vegetative-explant → PLB precedent while demonstrating strong explant dependence.

## Comparator 2 — *Ipsea malabarica*

Martin & Madassery (2005), *Rapid in vitro propagation of the threatened endemic orchid, Ipsea malabarica through protocorm-like bodies*, Indian Journal of Experimental Biology. PMID `16187536`.

This comparator is especially relevant because it is a threatened terrestrial orchid and the starting vegetative material was linked to field-grown rhizomes.

Abstract-verified evidence encoded:

- in vitro shoots were derived from **field-grown rhizomes**;
- axillary buds converted to PLBs on MS + **13.3 µM BA + 2% commercial-grade sugar**;
- PLB conversion began within **25 days**;
- a mean **33.1 PLBs** developed within 50 days;
- **kinetin did not induce PLBs**, although it supported axillary-bud proliferation;
- transfer on the BA/sugar medium produced a mean **47.5 PLBs**;
- half-strength MS + **6.97 µM kinetin** converted **98% of PLBs to plantlets**.

The explicit non-inductive kinetin treatment is preserved as first-class negative evidence.

## Comparator 3 — *Hemipilia cucullata*

Tu et al. (2025), *Asymbiotic Germination and Leaf Explant-Based Regeneration of the Endangered Medicinal Orchid Hemipilia cucullata from Mature Seeds*. DOI `10.3791/68541`; PMID `41052007`.

PubMed abstract evidence encoded:

- the species is an endangered terrestrial orchid;
- sterile leaf explants were used for PLB induction;
- the highest reported PLB-induction rate was **44.3 ± 5.1%**;
- the corresponding treatment was MS + **3 mg/L BA + 0.2 mg/L NAA**.

This adds a modern endangered-terrestrial example in which differentiated leaf tissue can be reprogrammed into PLBs.

## Comparator 4 — *Anoectochilus roxburghii*

Fu et al. (2026), *Efficient plant regeneration via protocorm-like body induction from stem nodes in Anoectochilus roxburghii*. DOI `10.1186/s12870-026-09210-5`.

The publisher open-access abstract provides the closest direct comparator to the proposed meristem question:

- stem segments with nodes were established as sterile starting material;
- PLBs were **directly induced from axillary-bud meristems without an intervening callus phase**;
- the reported optimal treatment was **1.5 mg/L 6-BA + 1.0 mg/L NAA + 0.1 mg/L kinetin**;
- the reported proliferation coefficient was **greater than 30**;
- the study concerns an endangered medicinal terrestrial orchid.

This is direct meristem → PLB precedent in another terrestrial orchid. It does not establish the pathway in *Thelymitra*.

## Implemented capability

`runtime/terrestrial_orchid_propagation_comparators.py` now provides:

- four independent terrestrial-orchid source records;
- nine explant/treatment/response observations;
- source-level DOI/PMID provenance;
- terrestrial/conservation-context flags;
- positive, low-frequency and negative treatment directions;
- explicit rhizome-linked and meristem comparator detection;
- deterministic source and observation hashes;
- a comparative matrix;
- a governed `vegetative_plb_bridge_assessment()`.

The bridge assessment may conclude only:

`documented_in_other_terrestrial_orchids`

It also exposes the strongest structural bridges separately:

- `direct_meristem_to_plb_comparator_ids = [ar-meristem-plb-001]`
- `rhizome_linked_vegetative_comparator_ids = [im-axillary-plb-001]`

It is permanently prohibited from converting these into:

- direct *Thelymitra* evidence;
- a probability of success for *T. variegata*;
- an automatically selected explant or medium;
- scientific publication authority;
- Knowledge Graph mutation authority.

## Scientific interpretation

The proposed *Thelymitra* vegetative-entry experiment is now supported by multiple forms of terrestrial-orchid precedent:

- node → PLB;
- leaf → PLB;
- root segment → PLB at low frequency;
- rhizome-linked in vitro shoot → axillary bud → PLB;
- axillary-bud meristem → direct PLB without callus.

This materially strengthens biological plausibility. At the same time, the variation among taxa and explants shows why direct protocol transfer is unsafe: *Spathoglottis* nodal tissue responded at 98.5% while its leaf tissue responded at 6.5%, whereas *Hemipilia* leaf explants reached 44.3 ± 5.1% under a different PGR regime.

The correct conclusion is therefore:

> Vegetative-to-PLB regeneration, including direct meristem-to-PLB regeneration, has terrestrial-orchid precedent. This makes the *Thelymitra* question biologically plausible and experimentally testable, but explant identity, genotype, developmental state, seasonality/dormancy, medium and PGR response remain species-specific unknowns.

## Validation

`tests/test_terrestrial_orchid_propagation_comparators.py` asserts:

- all four comparator taxa are represented as independent terrestrial-orchid evidence;
- *Spathoglottis* nodal evidence remains non-*Thelymitra* evidence;
- *Ipsea* positive BA and negative kinetin outcomes coexist;
- *Hemipilia* leaf-explant PLB induction and PGR values are preserved;
- *Anoectochilus* direct meristem-to-PLB evidence is represented without becoming a *Thelymitra* claim;
- the nine-row comparator matrix retains source provenance;
- the bridge assessment distinguishes meristem and rhizome-linked precedent while returning precedent rather than prediction.

The CALYX-639 focused CI workflow compiles the comparator module and includes this test suite. Exact-head GitHub Actions execution remains an external blocker until a run actually starts and succeeds.

## Next scientific work

1. Search specifically for geophytic/tuberous terrestrial orchids closer to Diurideae/Thelymitrinae.
2. Acquire full texts for the highest-proximity comparator studies before using exact media as experimental recommendations.
3. Add explant developmental state, sterilization, genotype, seasonality/dormancy and tuber/rhizome physiology when evidence supports them.
4. Combine comparator rows with full Davis et al. treatment rows only after source-specific provenance remains separable.
5. Use the resulting matrix to rank **questions requiring experiment**, not to generate unsupported propagation prescriptions.
