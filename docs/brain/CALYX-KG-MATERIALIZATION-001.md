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

`runtime/knowledge_graph/verified_dynamic_materializer.py` provides a conservative live verification path for exactly these two remaining audit domains. It examines only fixed candidate relations, requires stable record and canonical taxon identifiers on the same relation, validates SELECT-only SQL, requires at least one row to resolve to an existing persisted taxon node, preserves the complete relational row in graph payload provenance, runs bounded two-pass staging validation by default, and delegates authorized production writes to the same single-writer transactional publisher.

The production publisher was extended additively so a caller may supply an explicit reviewed SELECT-only query map. The default source-registry behavior remains unchanged.

Operators:

- `python scripts/materialize_dynamic_graph_relationship.py habitat`
- `python scripts/materialize_dynamic_graph_relationship.py elevation`

Both are read-only by default. Publication requires `--execute --confirm PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS` and remains an owner-governed production mutation.

## Persisted graph audit measures the real target

`app/readiness/live_graph_audit.py` has been upgraded from an image-only graph check to a complete persisted relationship audit covering taxonomy→images, occurrences, elevation, climate, literature, pollinators, mycorrhiza, habitat, conservation, plus Knowledge Graph node/edge integrity.

For canonical `oc_graph.kg_edges`, the audit counts actual graph predicates rather than inferring success from relational foreign keys. It reports explicit missing relationships and verifies null endpoints, orphan endpoints, and duplicate edges. Readiness cannot become green until every required persisted relationship is present and integrity passes.

`app/readiness/owner_audit_relationships.py` provides a pure adapter for Mission Control audits. It replaces the legacy behavior in which every relationship was listed as missing whenever any unrelated subsystem was incomplete. Its output is derived only from measured persisted graph state and is covered by regressions. Wiring that adapter into the large legacy Owner Operations module remains a mechanical integration step; the measurement contract itself is isolated and testable.

A dedicated read-only deployed graph audit operator is available:

`python scripts/audit_persisted_graph_relationships.py`

It queries PostgreSQL, emits the complete relationship/integrity report as JSON, performs no writes, and returns non-zero while required integrations remain incomplete.

## Calyx Speak consumes persisted graph context and literature metadata

`app/calyx_conversation/graph_context.py` adds a conservative read-only bridge from a scientific Speak turn to `oc_graph`.

The taxon bridge does not perform fuzzy identification. It extracts only explicit binomial names in the current user message, resolves them by exact case-insensitive `taxon` display label, and returns a bounded persisted graph traversal. No common-name inference or image-identification inference is used.

`app/calyx_conversation/graph_literature_search.py` adds a second read-only bridge for scientific questions that do not contain an explicit taxon name, such as foliar-nutrition questions. It performs bounded literal-term search over persisted `publication` nodes and their payload metadata, then follows incoming `documented_by` edges to report associated taxon provenance. It does not expand synonyms, does not claim full-text retrieval, and does not infer causal or physiological conclusions from publication titles or metadata.

`app/calyx_conversation/speak_routes.py` now adds both graph sources to the governed provider context. Stored message metadata records taxon-graph status and graph-literature search status/result counts. The epistemic policy marks persisted graph context and persisted publication-node metadata as governed Continuum evidence while retaining `knowledge_graph_mutation=False`.

The deterministic fallback provider is now `calyx-governed-summary-v3-graph-literature`. This matters because deployed Speak has been operating through the deterministic fallback. When semantic retrieval or a Brain mission returns no evidence but persisted graph evidence exists, fallback output now reports graph predicates/domain coverage and/or matching publication metadata instead of collapsing all of those states into a generic “no governed evidence” response. It explicitly warns that graph connectivity and title/metadata matches do not by themselves justify a new scientific conclusion and that the underlying paper text must still be inspected for substantive literature synthesis.

This closes the storage-only gap: once relationships and publication nodes exist in `oc_graph`, Speak has implemented read-only paths to consume both taxon-linked graph context and persisted literature metadata.

## Governance

This branch creates and hardens executable bridges but does not itself run against production. It does not bypass blocked source projections, publish staging-only science, activate taxonomy, infer fuzzy taxon crosswalks, or suppress source-contract failures.

Production Knowledge Graph publication remains owner-governed. A failed or rolled-back attempt is never reported as successful mutation. Speak graph access and graph-literature search are strictly read-only.

## Validation hardening completed

- fail closed for blocked/unverified static domains;
- explicit production domain selection and exact confirmation;
- bounded dry-run row ceilings and batch-size bounds;
- canonical two-pass staging validation;
- canonical single-writer transactional publisher reuse;
- rollback result cannot masquerade as graph mutation;
- complete nine-relationship persisted graph measurement;
- node/edge integrity measurement including orphan endpoints;
- regressions proving readiness reflects only actually absent relationships;
- Mission Control relationship-field adapter derived from measured graph evidence;
- read-only deployed graph audit operator;
- live-schema verification for habitat/elevation requiring same-table identity + taxon keys and taxon-resolved rows;
- full source-row preservation for dynamically projected habitat/elevation nodes;
- optional explicit reviewed query-map support in `publish_to_production` without changing its default registry path;
- exact-binomial-only Speak graph resolver and bounded traversal;
- bounded literal-term persisted publication-node search with taxon-link provenance;
- deterministic fallback graph-context and graph-literature reporting without promoting connectivity/title matches to scientific conclusions;
- focused unit/regression tests and dedicated CI coverage for all of the above.

## Current branch state

The integration is intentionally concentrated in one PR instead of spawning separate graph, audit, habitat/elevation, or Speak PRs. Re-check branch drift before merge; do not assume a prior zero-behind result remains current after later main activity.

## Current validation and merge boundary

GitHub-hosted Actions remains affected by the runner allocation incident. Recent branch workflows have produced jobs with `steps: null`; no checkout, compile, tests, Ruff, or graph regression commands executed. Zero-step failures are not accepted as validation evidence.

The branch therefore remains draft. It must not be merged merely because GitHub reports it as mergeable. Required next proof is executable exact-head validation through a trusted runner or a trusted local/deployed read-only validation path.

## Next integration work

1. Obtain exact-head executable validation when a trusted runner is available.
2. Run bounded read-only validation against the deployed database for the seven static verified domains.
3. Run read-only habitat and elevation discovery/dry-runs against the deployed database; either produce verified projections or return precise source/crosswalk blockers.
4. Run the persisted relationship audit against the deployed database and capture exact baseline counts.
5. Resolve source-contract failures rather than suppressing them.
6. With owner authorization, publish verified domains transactionally one domain at a time, beginning with literature and auditing after every slice.
7. Re-run live Speak acceptance for `Laelia anceps` and the foliar-nutrition literature question after graph publication; then separately repair/populate the semantic evidence index so full evidence-grounded synthesis can inspect underlying document text rather than relying on graph metadata alone.
