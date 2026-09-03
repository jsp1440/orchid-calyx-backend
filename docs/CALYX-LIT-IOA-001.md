# CALYX-LIT-IOA-001 — International Odontoglossum Alliance intake

Issue: #1236

This lane registers the International Odontoglossum Alliance as a bounded,
review-only literature corpus. It begins with the public culture page and uses
the site's publication master index, recent-journal page, archive indexes, and
historical indexes as discovery maps.

## Governance

- Site text and journal rights are `unknown_requires_review` unless a specific
  resource carries a verified license or written permission.
- Discovery records metadata only. It does not copy or publish journal PDFs.
- The culture page is converted to a deterministic UTF-8 projection for the
  existing exact-span literature pipeline. The source HTML hash, projection
  hash, source URL, retrieval time, rights state, and historical-taxonomy flag
  are retained.
- Every extracted claim enters the existing unreviewed queue. Publication
  decisions remain blocked, and this lane exposes no Knowledge Graph write.
- Names such as *Odontoglossum* are source-reported historical taxonomy until
  the governed taxonomy resolver binds them to a current concept.

## Bounded operator commands

Discover allowlisted site resources without downloading journal content:

```bash
python -m scripts.ingest_odontalliance_corpus \
  --mode discover \
  --output runtime/odontalliance-intake \
  --max-resources 250 \
  --max-bytes 25000000
```

Acquire and extract the culture page into a local review-only literature
bundle:

```bash
python -m scripts.ingest_odontalliance_corpus \
  --mode culture \
  --output runtime/odontalliance-intake \
  --max-bytes 2000000
```

Neither command writes to the production database, publishes to the Knowledge
Graph, changes taxonomy, or deploys an application. Re-running identical
culture bytes produces the same paper identity and projection path.
