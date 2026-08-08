# CALYX-639G — Thelymitrinae Propagation Evidence Gap

**Status:** implemented evidence-gap registry; direct same-subtribe vegetative evidence unresolved  
**Parent:** CALYX-639 / issue #639 / draft PR #640  
**Schema:** `calyx-thelymitrinae-propagation-evidence-gap/v1`

## Purpose

CALYX-639F established a strong proximal Australian Diurideae comparator in *Diuris longifolia*, including non-destructive inflorescence-derived PLB initiation. The next scientific question was whether direct vegetative-to-PLB or meristematic culture evidence could be verified inside the focal subtribe Thelymitrinae.

A targeted search was run for *Thelymitra*, *Calochilus* and *Epiblema* with tissue-culture, micropropagation, meristem, shoot-tip and protocorm-like-body terms.

## Search outcome

No directly reviewable source retrieved in this search established mature vegetative explant → PLB or meristematic micropropagation for Thelymitrinae independently of the Davis et al. seed/protocorm pathway.

This is encoded as:

`unresolved_source_acquisition_required`

It is **not** encoded as evidence that such work does not exist.

The system explicitly forbids:

- treating search non-retrieval as evidence of absence;
- upgrading *Diuris longifolia* evidence to same-subtribe support;
- selecting a *Thelymitra* explant automatically;
- generating a success probability;
- authorizing publication or canonical Knowledge Graph mutation.

## Highest-priority source lead

Yam & Arditti, *Micropropagation of Orchids*, Third Edition, has a dedicated **Thelymitra** section in the publisher table of contents. This is now the highest-priority acquisition lead because the accessible publisher record confirms taxon-specific coverage but does not expose enough text to determine whether the section contains vegetative, meristem, inflorescence, shoot-tip, PLB, seed-only, or protocorm-only methods.

Acquisition question:

> Does the Thelymitra section document any vegetative entry route into clonal culture, and if so, what explant, developmental state, medium, growth regulators and outcomes were reported?

The DBCA/Kings Park Queen of Sheba conservation summary remains a secondary lead. It confirms tissue-culture improvement work from very limited seed material but does not establish a mature vegetative entry route.

## Evidence ladder now enforced

1. **Same species — *Thelymitra variegata***: seed/protocorm → PLB pathway reported; mature vegetative entry unverified.
2. **Same subtribe — Thelymitrinae**: unresolved; targeted source acquisition required.
3. **Proximal core Diurideae — *Diuris longifolia***: non-destructive inflorescence tissue → PLB documented.
4. **Other terrestrial orchids**: vegetative and meristem → PLB documented across several taxa.

This hierarchy prevents broader evidence from silently gaining greater phylogenetic authority than it deserves.

## Implementation

`runtime/thelymitrinae_propagation_evidence_gap.py` provides:

- immutable acquisition-lead records;
- targeted-search state that distinguishes non-retrieval from evidence of absence;
- a four-level propagation evidence ladder;
- deterministic acquisition matrix hashes;
- explicit low-risk sampling priority: defer destructive tuber sampling until lower-risk routes have been reviewed.

`tests/test_thelymitrinae_propagation_evidence_gap.py` verifies all of those boundaries.

The CALYX-639 focused workflow now compiles the module and executes the new tests together with all prior propagation suites.

## Validation state

The immediately preceding CALYX-639F executable head passed all seven focused suites and the workflow-governance audit. CALYX-639G adds one isolated evidence-gap module, its deterministic tests, workflow inclusion and this Brain record. GitHub had not yet started an Actions run for the current CALYX-639G head when checked. CI for this exact head is therefore **pending/not yet evidenced**, not passed. PR #640 remains open, draft and mergeable; no merge or deployment is authorized.

## Next highest-value work

1. Acquire authorized access to the Yam & Arditti Thelymitra section.
2. Extract and source-locate every Thelymitra propagation method and distinguish seed/protocorm from vegetative/clonal entry.
3. Search cited references from that section recursively for older primary Thelymitra culture studies.
4. Acquire the complete Davis et al. paper and Collins & Dixon article text for full method extraction.
5. Do not select an experimental Queen of Sheba explant until this same-subtribe evidence gap has either been resolved or formally reviewed as unresolved.

No merge, deployment, scientific publication, destructive sampling or canonical Knowledge Graph mutation is authorized by this Brain record.
