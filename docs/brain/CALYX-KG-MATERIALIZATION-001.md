# CALYX-KG-MATERIALIZATION-001 — Verified cross-domain graph materialization

## Why this exists

The executive audit can report millions of source records while still reporting taxonomy-to-domain relationships as missing. Canonical main already contains domain adapters, verified SELECT-only source projections, graph publication infrastructure, staging validation, and a writable PostgreSQL graph repository. The missing operational bridge was a single governed path that actually uses those verified projections to materialize persistent `oc_graph` nodes and edges.

## Implemented

`runtime/knowledge_graph/production_materializer.py` connects the verified source registry directly to the canonical domain adapters.

Read-only validation reuses `run_controlled_dry_run`, which performs a two-pass idempotency check against an in-memory staging graph. It is bounded to 10,000 rows per selected domain by default so the multi-million-row media corpus cannot exhaust an operator process merely to prove the adapter path.

Production execution reuses `publish_to_production` rather than opening a writable repository directly. That existing canonical publisher:

- acquires the PostgreSQL single-writer publication lock;
- runs the selected adapters through `BuildOrchestrator`;
- validates the resulting graph;
- commits only when every selected domain completes and cross-domain validation is healthy;
- rolls the complete transaction back on a domain failure or unhealthy graph.

Production execution additionally requires:

1. an explicit `--domains` list;
2. `--execute`;
3. the exact confirmation token `PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS`.

The audit-priority verified domains are:

- media → `has_image`
- occurrences → `occurs_at`
- climate → `experiences_climate`
- literature → `documented_by`
- pollinators → `associated_with_pollinator`
- mycorrhiza → `associated_with_mycorrhiza`
- conservation → `has_conservation_assessment`

These domains already have verified source queries and adapters on canonical main. The materializer refuses domains such as habitat and elevation while their production projections remain unverified; it does not invent joins to make the audit look green.

## Persisted graph audit now measures the real integration target

`app/readiness/live_graph_audit.py` has been upgraded from an image-only graph check to a complete persisted relationship audit. It independently measures:

- `taxonomy_to_images`
- `taxonomy_to_occurrences`
- `taxonomy_to_elevation`
- `taxonomy_to_climate`
- `taxonomy_to_literature`
- `taxonomy_to_pollinators`
- `taxonomy_to_mycorrhiza`
- `taxonomy_to_habitat`
- `taxonomy_to_conservation`
- Knowledge Graph node/edge integrity

For canonical `oc_graph.kg_edges`, the audit counts the actual graph predicates rather than inferring success from relational foreign keys. It reports explicit missing relationships and verifies null endpoints, orphan endpoints, and duplicate edges. The readiness state cannot become green until every required persisted relationship is present and graph integrity passes.

This closes a second source of repeated false-negative/false-positive audit loops: relational linkage and graph materialization are now measured separately, and each of the executive-audit relationship targets has a persisted graph measurement.

## Operator

Bounded read-only proof across all audit-priority verified domains:

`python scripts/materialize_verified_graph_relationships.py`

Bounded read-only proof for a subset:

`python scripts/materialize_verified_graph_relationships.py --domains literature occurrences media`

Production publication is intentionally explicit and should normally be executed one verified domain at a time so failures are isolated and post-publication measurements are easy to interpret:

`python scripts/materialize_verified_graph_relationships.py --domains literature --execute --confirm PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS`

A production run reports `production_graph_mutation=true` only when the canonical transactional publisher reports `committed=true`. A failed/rolled-back attempt cannot be mislabeled as successful graph mutation.

## Governance

This branch creates and hardens the executable bridge but does not itself run against production. It does not bypass blocked source projections, publish staging-only science, activate taxonomy, infer missing taxon crosswalks, or suppress source-contract failures.

## Validation hardening completed in this branch

- fail closed for blocked/unverified domains;
- explicit production domain selection;
- exact confirmation requirement before the production publisher is called;
- bounded dry-run row ceiling;
- batch-size bounds;
- canonical two-pass dry-run reuse;
- canonical single-writer transactional production publisher reuse;
- regression proving rolled-back publication is not reported as graph mutation;
- complete nine-relationship persisted graph measurement;
- node/edge integrity measurement including orphan endpoints;
- regression proving readiness remains blocked for only the relationships that are actually absent;
- regression proving readiness can become green only when all required relationships and integrity exist.

## Next integration work

1. Obtain exact-head executable CI when GitHub Actions allocates a runner.
2. Run bounded read-only validation against the deployed database.
3. Resolve any source-contract failures rather than suppressing them.
4. With owner authorization, publish verified domains transactionally, preferably one domain at a time.
5. Re-run the persisted graph audit and Calyx scientific retrieval acceptance after each publication slice.
6. Verify real habitat and elevation source projections/crosswalks, then add them to the verified materialization set.
7. Feed persisted taxon-linked graph context into the live Calyx Speak evidence path so graph materialization is not merely stored but actually consumable by scientific conversation.
