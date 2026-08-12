-- CALYX-TIG-005 — governed molecular/genomic evidence layer
-- Candidate molecular associations remain outside live TIG evidence until explicit human review.

CREATE SCHEMA IF NOT EXISTS oc_genomics;

CREATE TABLE IF NOT EXISTS oc_genomics.molecular_evidence_candidates (
    association_id text PRIMARY KEY,
    canonical_taxon_id text NOT NULL,
    scientific_name text,
    evidence_kind text NOT NULL CHECK (evidence_kind IN ('genetic_association','expression_association','selection_association')),
    trait_predicate text NOT NULL,
    trait_value text,
    association_type text NOT NULL,
    gene_id text,
    protein_id text,
    sequence_accession text,
    pathway_id text,
    marker_name text,
    effect_value text,
    evidence_text text NOT NULL,
    method text,
    source_id text NOT NULL,
    source_uri text,
    doi text,
    pmid text,
    publication_id text,
    confidence_score double precision NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_state text NOT NULL DEFAULT 'candidate' CHECK (review_state IN ('candidate','accepted','rejected','needs_review')),
    reviewed_by text,
    reviewed_at timestamptz,
    review_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (gene_id IS NOT NULL OR protein_id IS NOT NULL OR pathway_id IS NOT NULL OR marker_name IS NOT NULL OR sequence_accession IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_tig_molecular_candidate_taxon
    ON oc_genomics.molecular_evidence_candidates (canonical_taxon_id);
CREATE INDEX IF NOT EXISTS idx_tig_molecular_candidate_review
    ON oc_genomics.molecular_evidence_candidates (review_state, evidence_kind);
CREATE INDEX IF NOT EXISTS idx_tig_molecular_candidate_doi
    ON oc_genomics.molecular_evidence_candidates (doi) WHERE doi IS NOT NULL;

CREATE OR REPLACE VIEW oc_genomics.trait_associations AS
SELECT
    association_id,
    canonical_taxon_id,
    scientific_name,
    trait_predicate,
    trait_value,
    association_type,
    gene_id,
    protein_id,
    sequence_accession,
    pathway_id,
    marker_name,
    effect_value,
    evidence_text,
    method,
    source_id,
    source_uri,
    doi,
    pmid,
    publication_id,
    confidence_score,
    review_state,
    provenance,
    reviewed_by,
    reviewed_at
FROM oc_genomics.molecular_evidence_candidates
WHERE review_state = 'accepted'
  AND evidence_kind IN ('genetic_association','selection_association');

CREATE OR REPLACE VIEW oc_genomics.expression_associations AS
SELECT
    association_id,
    canonical_taxon_id,
    scientific_name,
    trait_predicate,
    trait_value,
    association_type,
    gene_id,
    protein_id,
    sequence_accession,
    pathway_id,
    marker_name,
    effect_value,
    evidence_text,
    method,
    source_id,
    source_uri,
    doi,
    pmid,
    publication_id,
    confidence_score,
    review_state,
    provenance,
    reviewed_by,
    reviewed_at
FROM oc_genomics.molecular_evidence_candidates
WHERE review_state = 'accepted'
  AND evidence_kind = 'expression_association';

COMMENT ON TABLE oc_genomics.molecular_evidence_candidates IS
'Human-reviewed molecular/genomic candidate evidence for CALYX TIG. Candidate rows do not enter live TIG until review_state=accepted.';
