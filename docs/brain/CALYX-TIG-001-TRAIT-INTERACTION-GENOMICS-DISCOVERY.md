# CALYX-TIG-001 — Trait–Interaction–Genomics Discovery Engine

## Decision

The Orchid Continuum establishes a first-class Calyx Trait–Interaction–Genomics (TIG) Discovery Engine linking TraitBank-style phenotype assertions, ecological interactions, phylogeny-ready taxon scopes, and molecular/genomic evidence. The working scientific store is Neon/Postgres; public versioned scientific snapshots are prepared for Zenodo. Render disk is staging/cache only.

## Scientific purpose

The engine is intended to expose patterns that are difficult to see in siloed datasets: repeated pollinator-associated floral traits, repeated molecular features associated with those traits, convergent phenotype/genotype patterns, and candidate inheritance/selection relationships useful for evolutionary research and potentially breeding.

It is a hypothesis generator, not a causal oracle. Every generated hypothesis is non-causal by default and must retain provenance to its evidence records. Phylogenetic correction, replication, mechanism review, and publication governance are required before causal interpretation.

## Evidence model

Evidence records distinguish observed, inferred, and predicted traits from ecological interactions, genetic associations, expression associations, selection evidence, and phylogenetic evidence. Records retain source identifiers, sequence/gene/protein/pathway identifiers where available, method/context fields, confidence, and direct-observation status.

## Operational architecture

1. Harvest TraitBank/EOL and literature-derived traits.
2. Normalize ecological interactions through the relationship/GloBI layer without rejecting novel literature-supported interactions.
3. Attach molecular evidence from sequence, gene, protein, transcript/expression, and pathway sources.
4. Persist structured evidence and candidate hypotheses in Neon.
5. Run TIG discovery over taxon-scoped evidence matrices.
6. Keep candidates non-causal and route consequential claims through existing Calyx evidence/review/publication controls.
7. Build checksummed release packages and archive approved dataset versions through Zenodo.

## QUBIC relationship

QUBIC (QUalitative BIClustering) is a relevant external method for gene-expression biclustering. The initial TIG engine provides the provenance-aware cross-domain discovery substrate and deliberately does not claim to reproduce the published QUBIC algorithm. A later analysis adapter may invoke a validated QUBIC/Bioconductor workflow for expression matrices and feed resulting biclusters back as molecular evidence with software/version provenance.

## Storage policy

- Neon/Postgres: mutable structured evidence, review state, hypotheses, identifiers, provenance, graph references.
- Zenodo: approved versioned public scientific snapshots with DOI/version history.
- Object storage: permitted bulky source binaries when required.
- Render `/var/data`: temporary archive build/staging and cache only.

## Zenodo configuration

Runtime variables:

- `ZENODO_ACCESS_TOKEN` — secret token; required for API writes.
- `ZENODO_API_BASE` — defaults to `https://zenodo.org/api`; use sandbox during certification.
- `ZENODO_COMMUNITY` — Orchid Continuum community identifier once created.
- `CALYX_SCIENTIFIC_ARCHIVE_STAGING` — defaults to `/var/data/scientific_archive_staging`.

Publishing must remain an explicit authenticated action. Draft creation and release-package generation do not imply publication.

## Implementation

Module: `app/trait_genomics/`

- `models.py`: evidence, datasets, hypotheses and result contracts.
- `discovery.py`: conservative repeated-pattern discovery engine.
- `repository.py`: Neon/Postgres persistence tables and idempotent upserts.
- `zenodo.py`: checksummed release builder and Zenodo draft/publish bridge.
- `routes.py`: authenticated operational endpoints.

Tests cover repeated-pattern discovery, single-taxon suppression, non-causal policy, deterministic archive packaging, checksums, and Zenodo token gating.

## Governance invariants

1. Correlation is never silently promoted to causation.
2. Direct, inferred, and predicted traits remain distinguishable.
3. Novel interactions absent from GloBI are preserved with provenance rather than discarded.
4. Sequence and genomic identifiers must retain source/version provenance.
5. Zenodo public publication is explicit and separately authorized.
6. Published scientific snapshots are immutable/versioned; mutable review state remains in Neon.
