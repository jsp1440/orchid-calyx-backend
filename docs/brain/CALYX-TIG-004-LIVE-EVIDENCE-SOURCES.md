# CALYX-TIG-004 — Live Scientific Evidence Sources

## Purpose

Connect the Trait–Interaction–Genomics (TIG) discovery engine to the Orchid Continuum's live canonical scientific stores so discovery and Zenodo archive candidates can be produced from real evidence rather than caller-assembled or synthetic datasets.

## Canonical source hierarchy

TIG reads live evidence through a schema-tolerant, conservative adapter. Sources are selected in priority order and are never guessed from arbitrary table names.

### Traits

1. `oc_views.trait_resolved_v4`
2. `oc_traits.traits`

The resolved trait view is preferred because it is the canonical consensus surface already used by the scientific knowledge graph. TraitBank is an upstream source represented through the operational trait system; TIG does not bypass the canonical trait layer merely to reach the original bulk file.

### Ecological interactions

1. `oc_interactions.orchid_interaction_edges`
2. `oc_pollination.interactions`
3. `oc_globi.interactions`
4. `oc_interactions.taxon_interactions`

This permits GloBI-normalized interactions while retaining the Orchid Continuum's own canonical interaction surface. Novel literature-supported relationships may exist even when absent from GloBI and are not rejected solely for that reason.

### Molecular/genomic association evidence

Association tables are preferred when present:

- `oc_genomics.trait_associations`
- `oc_genomics.expression_associations`
- `oc_molecular.trait_associations`
- `oc_molecular.expression_associations`

These sources can satisfy the TIG molecular evidence domain only when a concrete gene, protein, pathway, named marker, or sequence feature is present.

### Phylogenetic sequence context

1. `oc_phylogeny.taxon_molecular_records`
2. `oc_phylogeny.taxon_sequences`

Raw sequence/marker presence is preserved as `phylogenetic_evidence`. It does **not** become `genetic_association` merely because a sequence exists for a taxon. This prevents the discovery engine from confusing routine phylogenetic sampling with evidence that a molecular feature is associated with a trait.

## Identity and normalization rules

Rows must contain a recognized canonical taxon identifier. Scientific names alone are not used to merge evidence across domains because synonymy, homonymy, and taxonomic drift could create false cross-domain joins. Rows lacking a canonical identifier are skipped and counted in diagnostics.

Source-supplied confidence values are retained when present. Missing confidence is assigned a conservative internal value of `0.5` and explicitly labeled `conservative_default_missing_source_confidence`; missing confidence is never interpreted as certainty.

Evidence IDs are deterministic. An explicit source identity is preferred; otherwise a SHA-256 digest of the canonicalized source row is used. Repeated evidence from overlapping views therefore does not inflate support merely because the live build is repeated.

## Live dataset identity

A live TIG dataset ID is derived from the sorted set of accepted evidence IDs. Identical scientific evidence therefore produces the same live dataset identity even when rebuilt later. This complements the Zenodo release fingerprint and allows the already-validated archive idempotency layer to prevent duplicate deposits.

## Discovery boundary

A TIG hypothesis still requires all three qualifying domains for each contributing taxon:

1. trait evidence;
2. ecological interaction evidence;
3. genetic or expression association evidence.

At least two taxa must show the same trait–interaction–molecular pattern before a candidate hypothesis is emitted. Raw phylogenetic sequence context does not satisfy requirement 3.

## API surfaces

- `GET /api/trait-genomics/live/readiness` — read-only inventory of the canonical live TIG sources and whether true three-domain discovery is currently possible.
- `POST /api/trait-genomics/live/dataset` — build a bounded live evidence snapshot with source diagnostics.
- `POST /api/trait-genomics/live/discover` — build the live snapshot, run TIG discovery, and optionally persist evidence/hypotheses to Neon/Postgres.
- `POST /api/trait-genomics/live/archive/zenodo-draft` — owner-session-only live evidence archive path. By default it refuses to create a Zenodo draft unless at least one real three-domain hypothesis exists.

The existing Zenodo publication endpoint remains disabled and the production Zenodo token remains draft-only.

## Governance

The live-source layer performs read-only access to the scientific domain stores. Its only writes are the already-governed TIG evidence/hypothesis persistence and, after explicit owner archive invocation, creation of an unpublished Zenodo draft plus the scientific archive ledger record.

No graph publication is performed by this module.
