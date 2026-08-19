# CALYX TIG-013 — Literature Evidence Routing

## Purpose

TIG-013 preserves scientifically useful orchid literature even when a paper does not satisfy the strict Trait–Interaction–Genomics molecular-association gate. Retrieved papers are classified into review-only evidence channels rather than discarded or misrepresented as gene–trait associations.

## Evidence routes

The deterministic router can classify a publication as:

- `molecular_association_candidate`
- `phylogenetic_sequence_context`
- `trait_morphology_evidence`
- `pollinator_selection_context`
- `pollination_ecology_evidence`
- `genomic_resource`
- `molecular_context`
- `general_orchid_literature`

Routing is descriptive. It does not establish causality and it does not make a record live TIG molecular evidence.

## Scientific boundary

A paper only receives `molecular_association_candidate` when the existing strict sentence-level molecular gate is satisfied. Sequence presence, phylogenetic markers, morphology, transcriptomic resources, or Europe PMC gene annotations by themselves do not satisfy that gate.

This means a phylogeny using ITS or `matK` can be retained as phylogenetic/sequence context while remaining excluded from the gene–trait association layer. Likewise, a labellum micromorphology paper can be retained as trait/morphology evidence without being promoted to a molecular association.

## Persistence

Review-only routes may be persisted to:

`oc_literature.evidence_route_candidates`

The table stores canonical taxon identity, publication identifiers, route, confidence, deterministic reasons, adaptive retrieval provenance, and review state. Route identifiers are deterministic from canonical taxon, source identity, and route.

The CLI is safe by default and does not write unless `--persist` is supplied.

## Production workflow

1. Resolve the scientific name against `public.orchid_taxonomy`.
2. Retrieve a bounded Europe PMC result set with TIG adaptive retrieval.
3. Inspect Europe PMC gene/protein annotations where available.
4. Evaluate the strict molecular-association gate.
5. Route every retrieved publication to the best evidence channel.
6. Optionally persist review-only routing records.
7. Keep all route candidates excluded from live TIG association evidence until governed review.

## CLI

Read-only routing:

```bash
PYTHONPATH=. python scripts/calyx_tig_route_literature.py \
  --name 'Dendrobium cuthbertsonii' \
  --page-size 10
```

Persist review-only routes only after inspecting the dry-run output:

```bash
PYTHONPATH=. python scripts/calyx_tig_route_literature.py \
  --name 'Dendrobium cuthbertsonii' \
  --page-size 10 \
  --persist
```
