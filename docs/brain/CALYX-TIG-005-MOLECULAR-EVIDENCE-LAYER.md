# CALYX-TIG-005 — Molecular Evidence Acquisition & Association Layer

## Purpose

CALYX TIG requires three evidence domains before it can propose cross-domain hypotheses: trait evidence, ecological interaction evidence, and molecular/genomic association evidence. Production readiness showed live traits and interactions but no legitimate molecular association source. TIG-005 supplies the governed persistence and review layer for that missing domain.

## Scientific boundary

Sequence presence is not trait causation. A GenBank accession, barcode, ITS region, plastid marker, transcriptome, or phylogenetic placement may provide molecular context, but it does not by itself establish that a gene, protein, pathway, expression pattern, or locus is associated with a phenotype. Molecular association evidence therefore enters a candidate table and is excluded from live TIG until explicit human scientific acceptance.

## Durable model

`oc_genomics.molecular_evidence_candidates` stores provenance-bearing candidate records with canonical taxon identity, phenotype/trait predicate, molecular feature identifiers, evidence excerpt, source identifiers, confidence, and review state.

Two live views expose only accepted evidence:

- `oc_genomics.trait_associations` — reviewed genetic/selection associations.
- `oc_genomics.expression_associations` — reviewed expression associations.

The existing live TIG adapter already searches these canonical source names. As soon as reviewed records exist, `/api/trait-genomics/live/readiness` can discover the molecular domain without weakening the three-domain gate.

## Governance

Candidate creation and review are owner-session operations. New records default to `candidate`. Only `accepted` rows enter the live views. Rejection and `needs_review` states remain preserved. Acceptance means evidence is sufficiently documented for TIG correlation analysis; it does not establish causation or authorize Knowledge Graph publication.

## APIs

- `GET /api/trait-genomics/molecular/status`
- `POST /api/trait-genomics/molecular/candidates`
- `POST /api/trait-genomics/molecular/candidates/{association_id}/review`

## Evidence identifiers

At least one molecular feature is mandatory: gene, protein, pathway, named marker, or sequence accession. Candidate IDs are deterministic SHA-256-derived identifiers when an upstream stable association ID is unavailable, making ingestion idempotent.

## Selection associations

`selection_association` is retained as a distinct EvidenceKind and is now counted as molecular evidence by the TIG discovery engine. This permits future tests of pollinator-mediated selection signatures while preserving the requirement for direct evidence and subsequent phylogenetic/mechanistic review.

## Next acquisition work

Populate the candidate layer from provenance-rich literature extraction and curated external molecular resources. Priority identifier systems include NCBI Gene, GenBank, SRA/BioProject, UniProt, GO, KEGG, DOI and PMID. Automated extraction may propose candidates, but human acceptance remains mandatory before those records can influence TIG discovery.
