# CALYX-639H — Same-Genus Thelymitra Recovery Evidence

**Status:** implemented; historical recovery evidence added; propagation method unresolved  
**Parent:** CALYX-639 / issue #639 / draft PR #640  
**Schema:** `calyx-thelymitrinae-propagation-evidence-gap/v2`

## New evidence

A targeted search recovered a stronger same-genus source than the prior evidence-gap record: the Australian Government/Department of Conservation and Land Management 1999 interim recovery plan for the Cinnamon Sun Orchid, *Thelymitra manginii*.

The recovery plan reports that the Botanic Gardens and Parks Authority (BGPA) was conducting genetic and propagation research on *T. manginii* and had **successfully propagated the species ex situ**. It also records a 1997 research translocation in which **25 dormant tubers** derived from material originally collected from a known population were planted back into that population.

The plan separately prioritizes collection of seed and cutting material and states that, if viable seed is inadequate, conservation could investigate living collections from other source material such as tubers or storage of tissue-culture material.

## Critical interpretation boundary

This is stronger than a generic proposal to propagate *Thelymitra*: successful same-genus ex-situ propagation is explicitly documented.

However, the recovery plan does **not** state how the propagated plants or the 25 translocation tubers were produced. It does not establish that they came from meristem culture, inflorescence culture, shoot-tip culture, direct tuber division, seed/protocorm culture, symbiotic culture, or another route.

Therefore the system state is:

`same_genus_ex_situ_success_documented_method_unresolved`

and **not**:

`same_genus_vegetative_micropropagation_verified`.

The source must never be used to infer a mature-tuber or meristem protocol without recovering BGPA technical records or primary propagation methods.

## Evidence ladder update

The propagation evidence hierarchy is now:

1. **Same species — *Thelymitra variegata***: seed/protocorm → secondary PLB pathway reported; mature vegetative entry unverified.
2. **Same genus — *Thelymitra***: *T. manginii* successful ex-situ propagation and dormant-tuber translocation documented; propagation route unresolved.
3. **Same subtribe — Thelymitrinae**: direct vegetative micropropagation remains unresolved.
4. **Proximal core Diurideae — *Diuris longifolia***: non-destructive inflorescence-derived tissue → PLB documented.
5. **Other terrestrial orchids**: vegetative and meristem → PLB documented across several taxa.

This finer hierarchy prevents historical same-genus recovery success from being lost while also preventing it from being overinterpreted.

## Source-acquisition implications

Two acquisition targets are now co-critical:

- Yam & Arditti, *Micropropagation of Orchids*, Third Edition, **Thelymitra** section (publisher contents place it on a single page in the genus-specific methods chapter). Its references may identify older primary *Thelymitra* propagation studies.
- BGPA/Kings Park technical records underlying the *T. manginii* propagation and 1997 translocation. These records may reveal whether the propagated material was seed-derived, symbiotic, asymbiotic, vegetative, tuber-derived, or tissue-cultured.

The government recovery plan is now preserved as an acquisition lead with `direct_vegetative_evidence_verified=False`.

## Mission Control integration

The protected science API now exposes:

- `GET /api/science/propagation/queen-of-sheba/evidence/thelymitrinae/search-state`
- `GET /api/science/propagation/queen-of-sheba/evidence/thelymitrinae/acquisition-matrix`
- `GET /api/science/propagation/queen-of-sheba/evidence/ladder`

These endpoints expose the same-genus success record, unresolved method state, three acquisition leads, and five-level evidence ladder while retaining `publication_authority=False` and no canonical Knowledge Graph mutation authority.

## Experimental implication

This evidence strengthens the case that *Thelymitra* itself has already been successfully propagated for conservation and translocation. It does **not** yet tell us which explant or culture route to use for Queen of Sheba.

The current low-risk decision remains unchanged: do not sacrifice a rare *T. variegata* tuber for method development while same-genus technical records and lower-risk above-ground routes remain unreviewed.

## Validation plan

Focused tests now verify:

- successful same-genus propagation is visible;
- the propagation method remains unresolved;
- the government recovery plan remains a non-vegetative acquisition lead;
- same species, same genus, same subtribe, proximal Diurideae, and broader terrestrial evidence stay separate;
- Mission Control exposes the ladder without protocol-selection, publication, or Knowledge Graph authority.

No merge, deployment, destructive sampling, scientific publication, or canonical Knowledge Graph mutation is authorized by this record.
