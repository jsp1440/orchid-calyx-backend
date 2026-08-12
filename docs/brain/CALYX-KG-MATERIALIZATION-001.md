# CALYX-KG-MATERIALIZATION-001 — Verified cross-domain graph materialization

## Why this exists

The executive audit can report millions of source records while still reporting taxonomy-to-domain relationships as missing. Canonical main already contains domain adapters, verified SELECT-only source projections, graph publication infrastructure, staging validation, and a writable PostgreSQL graph repository. The missing operational bridge was a single governed path that actually uses those verified projections to materialize persistent `oc_graph` nodes and edges.

## Static verified-domain materialization

`runtime/knowledge_graph/production_materializer.py` connects the verified source registry directly to the canonical domain adapters.

Read-only validation reuses `run_controlled_dry_run`, which performs a two-pass idempotency check against an in-memory staging graph. It is bounded to 10,000 rows per selected domain by default so the multi-million-row media corpus cannot exhaust an operator process merely to prove the adapter path.

Production execution reuses `publish_to_production`. The canonical publisher acquires the PostgreSQL single-writer publication lock, runs the selected adapters through `BuildOrchestrator`, validates the resulting graph, commits only when every selected domain completes and cross-domain validation is healthy, and rolls the complete transaction back on failure.

Production execution additionally requires an explicit `--domains` list, `--execute`, and the exact confirmation token `PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS`.

The static audit-priority verified domains are:

- media → `has_image`
- occurrences → `occurs_at`
- climate → `experiences_climate`
- literature → `documented_by`
- pollinators → `associated_with_pollinator`
- mycorrhiza → `associated_with_mycorrhiza`
- conservation → `has_conservation_assessment`

## Habitat and elevation: verified live-schema projection

Habitat and elevation are configured production domains and already have canonical graph vocabulary/adapters, but they do not have frozen static source queries. They are therefore not guessed into the static registry.

`runtime/knowledge_graph/verified_dynamic_materializer.py` now provides a conservative live verification path for exactly these two remaining audit domains.

For each domain it:

1. examines only fixed candidate relations already listed in `DOMAIN_TABLE_CANDIDATES`;
2. requires the stable record identifier and canonical taxon identifier to coexist on the same relation;
3. builds a SELECT-only projection and passes it through the canonical SQL safety validator;
4. requires at least one projected row to resolve to an existing persisted `taxon` node before the projection becomes executable;
5. preserves the complete relational row inside the graph node payload as source provenance;
6. runs bounded two-pass staging validation by default;
7. requires the same exact publication confirmation for production;
8. delegates production writes to the same single-writer, all-or-nothing publisher.

The production publisher was extended additively so a caller may supply an explicit reviewed SELECT-only query map. The default registry behavior is unchanged. This makes a live-verified projection usable transactionally without weakening the frozen static registry.

Operators:

- `python scripts/materialize_dynamic_graph_relationship.py habitat`
- `python scripts/materialize_dynamic_graph_relationship.py elevation`

Both commands are read-only by default. Publication requires `--execute --confirm PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS` and remains an owner-governed production mutation.

## Persisted graph audit measures the real target

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

For canonical `oc_graph.kg_edges`, the audit counts actual graph predicates rather than inferring success from relational foreign keys. It reports explicit missing relationships and verifies null endpoints, orphan endpoints, and duplicate edges. Readiness cannot become green until every required persisted relationship is present and graph integrity passes.

`app/readiness/owner_audit_relationships.py` provides a pure adapter for Mission Control audits. It replaces the legacy behavior in which every relationship was listed as missing whenever any unrelated subsystem was incomplete. Its output is derived only from measured persisted graph state and is covered by regressions. Wiring that adapter into the large legacy Owner Operations module remains a mechanical integration step; the measurement contract itself is isolated and testable.

A dedicated read-only deployed graph audit operator is available:

`python scripts/audit_persisted_graph_relationships.py`

It queries PostgreSQL, emits the complete relationship/integrity report as JSON, performs no writes, and returns non-zero while required integrations remain incomplete.

## Governance

This branch creates and hardens executable bridges but does not itself run against production. It does not bypass blocked source projections, publish staging-only science, activate taxonomy, infer fuzzy taxon crosswalks, or suppress source-contract failures.

Production Knowledge Graph publication remains owner-governed. A failed or rolled-back attempt is never reported as successful mutation.

## Validation hardening completed

- fail closed for blocked/unverified static domains;
- explicit production domain selection;
- exact confirmation before production publication;
- bounded dry-run row ceilings and batch-size bounds;
- canonical two-pass staging validation;
- canonical single-writer transactional publisher reuse;
- regression proving rolled-back publication is not reported as graph mutation;
- complete nine-relationship persisted graph measurement;
- node/edge integrity measurement including orphan endpoints;
- regressions proving readiness reflects only actually absent relationships;
- Mission Control relationship-field adapter derived from measured graph evidence;
- read-only deployed graph audit operator;
- live-schema verification for habitat/elevation requiring same-table identity + taxon keys and at least one taxon-resolved row;
- full source-row preservation for dynamically projected habitat/elevation nodes;
- optional explicit reviewed query-map support in `publish_to_production` without changing its default registry path;
- dedicated dynamic materializer tests and CI coverage.

## Current validation boundary

GitHub-hosted Actions remains affected by the runner allocation incident. Recent branch workflows have produced a job with `steps: null`; that means no checkout, compile, tests, Ruff, or graph regression commands executed. Zero-step failures are not accepted as validation evidence.

## Next integration work

1. Obtain exact-head executable CI when GitHub Actions allocates a runner.
2. Run bounded read-only validation against the deployed database for the seven static verified domains.
3. Run read-only habitat and elevation discovery/dry-runs against the deployed database; either produce verified projections or return precise source/crosswalk blockers.
4. Run the persisted relationship audit against the deployed database and capture exact baseline counts.
5. Resolve source-contract failures rather than suppressing them.
6. With owner authorization, publish verified domains transactionally one domain at a time, beginning with literature and auditing after every slice.
7. Feed persisted taxon-linked graph context into the live Calyx Speak evidence path so graph materialization is actually consumed by scientific conversation.
