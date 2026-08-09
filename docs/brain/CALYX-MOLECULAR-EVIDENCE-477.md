# CALYX-477 — Molecular, sequence, voucher, and phylogenetic evidence foundation

Status: IMPLEMENTED / VALIDATION PENDING / REVIEW-GOVERNED

## Delivered

- Owner-scoped molecular evidence records with accession identity, marker, source database, voucher metadata, specimen provenance, submitted taxon name, canonical taxon resolution, exact evidence span, confidence, conflicts, and review state.
- Explicit ambiguity queue for unresolved or conflicting taxon identities.
- Immutable alignment/analysis artifact registration through the existing Calyx artifact registry with evidence URI binding.
- Candidate phylogenetic-claim records with analysis-artifact references, evidence span, confidence, conflicts, human review history, and `truth_status=not_asserted` until reviewed.
- Human review transitions for sequence evidence and phylogenetic claims.
- Protected Mission Control routes for evidence registration, artifact binding, claim recording/review, ambiguity queue, and readiness.
- Deterministic bounded fixtures centered on an orchid ITS/voucher record; no live external sequence retrieval occurs.

## Scientific governance

`accepted_as_evidence` means a human reviewer has accepted the record as usable evidence. It does not mean the relationship is canonical phylogenetic truth. Even reviewed claims retain `truth_status=reviewed_evidence_only` and carry `scientific_publication_authorized=false` and `production_graph_mutation_authorized=false`.

Unresolved taxonomy cannot be promoted to accepted evidence. Conflicts and ambiguous names remain review inputs. The build does not infer taxonomic identity from sequence similarity and does not perform sequence alignment or tree inference itself.

## Permanent boundaries

No live sequence harvesting, phylogenetic truth assertion, scientific publication, production Knowledge Graph mutation, deployment, or merge authority is implemented.

## Validation

Focused tests cover provenance preservation, ambiguity routing, review gating, immutable analysis-artifact binding, candidate phylogenetic claims, owner isolation, and permanent non-publication/non-graph-mutation boundaries. Hosted GitHub Actions validation is currently subject to the repository-wide pre-step runner provisioning failure; exact-head evidence is recorded separately.
