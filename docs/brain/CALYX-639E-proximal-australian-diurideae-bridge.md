# CALYX-639E — Proximal Australian Diurideae Propagation Bridge

**Status:** implemented; comparator evidence; scientific review required  
**Parent:** CALYX-639 / issue #639 / draft PR #640  
**Schema:** `calyx-australian-diurideae-propagation-bridge/v1`

## Why this slice exists

The earlier CALYX-639B comparator set established that vegetative and meristematic tissues can enter protocorm-like-body (PLB) pathways in terrestrial orchids. The next priority was to reduce phylogenetic and ecological distance from *Thelymitra variegata*.

A substantially closer precedent is Collins & Dixon (1992), *Micropropagation of an Australian terrestrial orchid Diuris longifolia R. Br.*, Australian Journal of Experimental Agriculture 32:131–135, DOI `10.1071/EA9920131`.

The study was conducted at Kings Park and Botanic Garden, Western Australia—the same institutional conservation lineage now associated with the Queen of Sheba work.

## Why *Diuris longifolia* is unusually relevant

*Diuris longifolia* is:

- an Australian terrestrial orchid;
- a tuberous geophyte;
- native to south-western Western Australia;
- a member of tribe Diurideae, subtribe Diuridinae.

*Thelymitra* belongs to Thelymitrinae. Diuridinae is a proximal core-Diurideae lineage outside the clade containing Thelymitrinae. This does not make *Diuris* a physiological surrogate for *Thelymitra*, but it is a much closer phylogenetic comparator than the previously encoded *Spathoglottis*, *Ipsea*, *Hemipilia*, and *Anoectochilus* taxa.

Current Kew/POWO treatment accepts *Diuris longifolia* R.Br. as a species and describes it as a tuberous geophyte native to south-western Australia.

## Collins & Dixon evidence encoded

The author-uploaded article text/publisher preview reports a micropropagation strategy explicitly intended to avoid sacrificing the parent plant.

Three bounded observations are represented:

1. **Basal section of unopened flower bud → PLB**
   - inflorescence-derived explant from an intact field plant;
   - modified Burgeff N3f / Pa5 culture context;
   - reported initiation/proliferation treatment included 10 µM benzyladenine;
   - PLBs formed after 49 days.

2. **Axillary node from inflorescence → PLB**
   - likewise obtained from the inflorescence rather than the underground tuber;
   - PLBs formed after 49 days;
   - parent-plant destruction was not required.

3. **PLB-derived shoot → roots**
   - 10–20 mm shoots transferred to a reported coconut-water-containing, cytokinin-free rooting treatment;
   - root formation reported after 70 days.

The most important result for CALYX-639 is not the exact medium. It is that **somatic tissue from the reproductive shoot of a Western Australian tuberous Diurideae orchid could be taken without destroying the underground plant and induced into a PLB propagation pathway.**

## Scientific boundary

CALYX-639E is allowed to conclude:

`non-destructive somatic PLB initiation is documented in a phylogenetically proximal Australian tuberous Diurideae orchid`

It is not allowed to conclude:

- that *Thelymitra variegata* inflorescence tissue will respond similarly;
- that flower-bud base or inflorescence node is the preferred *Thelymitra* explant;
- that 10 µM BA should be transferred directly into a Queen of Sheba protocol;
- that a numerical probability of *Thelymitra* success can be inferred;
- that destructive sampling of a rare Queen of Sheba tuber is justified.

## Implementation

`runtime/australian_diurideae_propagation_bridge.py` provides:

- source-level DOI/institution/taxon/growth-form provenance;
- three bounded treatment-response observations;
- cryptographic source and observation digests;
- a `phylogenetic_bridge()` that distinguishes same-tribe proximity from same-subtribe evidence;
- a `non_destructive_bridge_assessment()` that reports precedent without selecting a *Thelymitra* explant;
- a deterministic bridge matrix.

`tests/test_australian_diurideae_propagation_bridge.py` asserts that:

- *Diuris longifolia* is represented as Diurideae/Diuridinae and tuberous;
- both non-destructive PLB-forming explants remain explicit;
- 49-day PLB formation is retained;
- Thelymitrinae and Diuridinae are never collapsed into one subtribe;
- method transfer and success probability remain false;
- no *Thelymitra* explant is automatically recommended;
- source/observation hashes remain deterministic.

The CALYX-639 focused CI workflow now compiles this module and runs the sixth focused test group.

## Research implication

This materially changes the experimental design space. Before risking underground Queen of Sheba material, a future reviewed pilot should explicitly consider whether a renewable above-ground explant can be tested first. The *Diuris* result demonstrates that this strategy has precedent in a related Australian tuberous terrestrial orchid.

That is a hypothesis-prioritization result, not a protocol prescription.

## Next priority

1. Search specifically for *Thelymitra*, *Calochilus*, *Epiblema*, Drakaeinae, and other core-Diurideae vegetative micropropagation evidence.
2. Acquire the complete Collins & Dixon article into the Literature Pipeline if not already available and extract all treatment/sterilization/acclimatization details with source locators.
3. Acquire the complete Davis et al. Queen of Sheba paper.
4. Build an explant-risk hierarchy that favors renewable above-ground material before tuber or meristem sacrifice, but only after direct evidence review.
5. Keep all cross-species medium transfer as a reviewed experiment-design question rather than an automatic recipe.
