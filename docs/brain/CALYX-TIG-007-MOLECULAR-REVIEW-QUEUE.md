# CALYX-TIG-007 — Molecular Evidence Review Queue

## Purpose

TIG-006 can discover literature-supported molecular association candidates, but those candidates must remain inspectable before any scientific acceptance. TIG-007 adds a bounded read-only review queue over `oc_genomics.molecular_evidence_candidates`.

## Query surface

The queue supports exact review-state, evidence-kind, canonical taxon ID, and source ID filters; a case-insensitive scientific-name search; minimum confidence; and bounded pagination. Query values remain database parameters rather than SQL fragments.

Default page size is 50 and maximum page size is 200. Queue order prioritizes `needs_review`, then `candidate`, then accepted/rejected records, with higher-confidence records first inside each review state.

The same service is available through the owner-authenticated API:

`GET /api/trait-genomics/molecular/candidates`

Supported query parameters are `review_state`, `evidence_kind`, `canonical_taxon_id`, `scientific_name`, `source_id`, `min_confidence`, `limit`, and `offset`. The endpoint requires the existing owner session in addition to the trait-genomics router authentication boundary.

## Governance

Reading the queue does not alter review state. The queue response explicitly reports `review_required=true` and `publication_enabled=false`. Acceptance/rejection remains the existing explicit owner review operation from TIG-005.

## Render operator command

Show the current candidate queue:

```bash
python scripts/calyx_tig_molecular_review_queue.py --state candidate --limit 50
```

Filter a taxon by scientific name:

```bash
python scripts/calyx_tig_molecular_review_queue.py \
  --state candidate \
  --scientific-name 'Dendrobium' \
  --min-confidence 0.5 \
  --limit 50
```

The command is read-only apart from idempotent schema assurance inherited from the molecular evidence repository.

## Next integration

The next UI step is a review-console surface over this API and the existing explicit review action. It must preserve the same human-review boundary and must not add automatic acceptance or publication behavior.
