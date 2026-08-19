# CALYX TIG-014 — Title-Aware Multi-Evidence Literature Routing

## Purpose

TIG-014 refines the review-only literature evidence router after live production validation with *Dendrobium cuthbertsonii*. A retrieved paper on labellum micromorphology was correctly useful scientific evidence but had been assigned `phylogenetic_sequence_context` as its primary route because phylogenetic sequence terminology occurred in the abstract.

The router now distinguishes a paper's primary scientific purpose from secondary methods or supporting context.

## Primary-route policy

The strict molecular-association gate remains highest priority. If that gate passes, the paper is still only a `molecular_association_candidate` pending human review.

When the strict molecular gate does not pass, explicit scientific-domain signals in the title are treated as stronger evidence of the paper's principal purpose than secondary terminology present only in the abstract. In particular:

- title-level morphology or micromorphology can make `trait_morphology_evidence` the primary route even when ITS, matK, phylogeny, or other sequence context appears in the abstract;
- title-level phylogenetic terminology can make `phylogenetic_sequence_context` primary;
- title-level genome/transcriptome terminology can make `genomic_resource` primary;
- title-level pollination terminology can strengthen pollinator-selection routing when association language and molecular context are also present.

No fuzzy scientific inference is introduced by this change. Routing remains deterministic and descriptive.

## Secondary evidence domains

Scientific papers can support more than one Orchid Continuum subsystem. TIG-014 therefore preserves other detected evidence channels as `secondary_routes` in provenance. Examples include:

- morphology paper with ITS/phylogenetic methods: primary `trait_morphology_evidence`, secondary `phylogenetic_sequence_context`;
- phylogeny paper containing useful morphology discussion: primary `phylogenetic_sequence_context`, secondary `trait_morphology_evidence`;
- morphology paper containing molecular annotations without a qualifying trait association: primary morphology route, secondary `molecular_context`.

Secondary routes are context only. They do not create accepted molecular evidence, causal claims, or live TIG eligibility.

## Live validation regression

The regression suite now includes the production pattern observed for the Europe PMC paper identified as PMC9455781 / PMID 36706796. A title centered on labellum micromorphology with ITS/phylogenetic context in the abstract must route primarily to `trait_morphology_evidence` while preserving `phylogenetic_sequence_context` as a secondary route.

## Governance boundary

All evidence-route records remain review-only. Persistence, when explicitly enabled, stores descriptive routing candidates in `oc_literature.evidence_route_candidates`. Routing does not promote a paper into accepted TIG molecular evidence and does not imply causality.