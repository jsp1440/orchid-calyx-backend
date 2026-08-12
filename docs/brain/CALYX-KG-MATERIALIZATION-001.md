# CALYX-KG-MATERIALIZATION-001 — Verified cross-domain graph materialization

## Why this exists

The executive audit can report millions of source records while still reporting taxonomy-to-domain relationships as missing. Current main already contains domain adapters, verified SELECT-only source projections, a graph publisher, dry-run staging, and a writable PostgreSQL graph repository. The missing operational bridge was a single governed path that actually uses those verified projections to materialize persistent `oc_graph` nodes and edges.

## Implemented

`runtime/knowledge_graph/production_materializer.py` now connects the verified source registry directly to the canonical domain adapters and BuildOrchestrator.

Default execution is read-only DRY_RUN. Production PUBLISH requires both `execute=True` and exact confirmation token `PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS` before a writable graph repository is opened.

The audit-priority verified domains are:

- media → `has_image`
- occurrences → `occurs_at`
- climate → `experiences_climate`
- literature → `documented_by`
- pollinators → `associated_with_pollinator`
- mycorrhiza → `associated_with_mycorrhiza`
- conservation → `has_conservation_assessment`

These domains already have verified source queries and adapters on canonical main. The materializer refuses domains such as habitat/elevation while their production projections remain unverified; it does not invent joins to make the audit look green.

## Operator

Read-only proof:

`python scripts/materialize_verified_graph_relationships.py`

Explicit publication after trusted validation and owner approval:

`python scripts/materialize_verified_graph_relationships.py --execute --confirm PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS`

A subset may be selected with `--domains literature occurrences media`.

## Governance

This change creates the executable bridge but does not itself run against production. It does not bypass blocked source projections, publish staging-only science, activate taxonomy, or infer missing taxon crosswalks.

## Next integration work

1. Run exact-head executable tests when GitHub Actions allocates a runner.
2. Run the read-only materialization proof against the deployed database.
3. Resolve any source-contract failures rather than suppressing them.
4. With owner authorization, run the production publication command for verified domains.
5. Re-run persisted graph audit and Calyx scientific retrieval acceptance.
6. Implement/verify habitat and elevation source projections, then add them to the verified materialization set.
