"""BUILD-066 tests: full graph-completion reporting + population invariants.

Covers domain coverage, per-taxon graph completeness, review queues,
idempotency of a full staging population, and resume/checkpoint recovery.
All tests run against the in-memory repository — no production writes.
"""

from __future__ import annotations

from runtime.knowledge_graph import (
    BuildOrchestrator,
    ExecutionMode,
    InMemoryCheckpointStore,
    InMemoryGraphRepository,
    InMemorySourceProvider,
    Edge,
    Node,
    domain_coverage_report,
    graph_completeness_report,
    registry_by_domain,
    review_queues,
)
from runtime.knowledge_graph.checkpoint import STATUS_SKIPPED


# --- fixtures ---------------------------------------------------------------

def _taxon(node_id: int, pk: str, label: str) -> Node:
    return Node(kg_node_id=node_id, node_type="taxon", canonical_key=f"taxon:{pk}",
                display_label=label, source_table="oc_graph.kg_nodes", source_pk=pk)


def _taxonomy_repo() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(nodes=[
        _taxon(1, "10", "Cattleya labiata"),
        _taxon(2, "11", "Cattleya mossiae"),
        _taxon(3, "12", "Dendrobium nobile"),
    ])


def _source() -> InMemorySourceProvider:
    return InMemorySourceProvider({
        "occurrences": [
            {"source_pk": "occ1", "taxon_pk": "10", "locality": "Brazil"},
            {"source_pk": "occ2", "taxon_pk": "11", "locality": "Venezuela"},
        ],
        "traits": [
            {"source_pk": "tr1", "taxon_pk": "10", "trait_name": "flower_color"},
        ],
        "media": [
            {"source_pk": "m1", "taxon_pk": "10", "caption": "bloom"},
        ],
    })


def _full_run():
    repo = _taxonomy_repo()
    orch = BuildOrchestrator(repo, _source(), checkpoint_store=InMemoryCheckpointStore(),
                             batch_size=100)
    report = orch.run(ExecutionMode.DRY_RUN)
    return orch, report


# --- domain coverage --------------------------------------------------------

def test_domain_coverage_reports_every_adapter_domain():
    _, report = _full_run()
    cov = domain_coverage_report(report["per_domain"], registry_by_domain())
    domains = {d["domain"] for d in cov["per_domain"]}
    assert {"occurrences", "traits", "media"} <= domains
    occ = next(d for d in cov["per_domain"] if d["domain"] == "occurrences")
    assert occ["records_connected"] == 2
    assert occ["edges_published"] == 2
    assert cov["totals"]["edges_published"] >= 4


def test_domain_coverage_carries_registry_strategy():
    _, report = _full_run()
    cov = domain_coverage_report(report["per_domain"], registry_by_domain())
    occ = next(d for d in cov["per_domain"] if d["domain"] == "occurrences")
    assert occ["connectivity_strategy"] in {"direct", "resolved_view", "name_join"}


# --- graph completeness -----------------------------------------------------

def test_completeness_counts_connected_and_unconnected_taxa():
    orch, _ = _full_run()
    comp = graph_completeness_report(orch.last_target_repo)
    agg = comp["aggregate"]
    assert agg["total_canonical_taxa"] == 3
    # Cattleya labiata (occ+trait+media) and mossiae (occ) are connected;
    # Dendrobium nobile has no domain data.
    assert agg["taxa_with_at_least_one_domain"] == 2
    assert agg["taxa_fully_unconnected"] == 1
    assert 0 < agg["overall_completion_pct"] < 100


def test_completeness_per_taxon_lists_connected_and_missing_domains():
    orch, _ = _full_run()
    comp = graph_completeness_report(orch.last_target_repo)
    by_label = {p["taxon_label"]: p for p in comp["per_taxon"]}
    labiata = by_label["Cattleya labiata"]
    assert set(labiata["connected_domains"]) == {"occurrences", "traits", "media"}
    assert labiata["relationship_count"] == 3
    nobile = by_label["Dendrobium nobile"]
    assert nobile["connected_domains"] == []
    assert "occurrences" in nobile["missing_domains"]


# --- review queues ----------------------------------------------------------

def test_review_queues_surface_conflicts_and_warnings():
    conflicts = {
        "duplicate_accepted_taxa": [{"canonical_name": "X", "canonical_ids": [1, 2]}],
        "unresolved_synonym_chains": [{"synonym": "a", "points_to": "b"}],
        "authority_disagreements": [],
    }
    per_domain = [{"domain": "literature", "status": "completed",
                   "warnings": ["5 source names did not resolve"], "error": None}]
    rq = review_queues(conflicts, per_domain)
    assert rq["summary"]["duplicate_accepted_taxa"] == 1
    assert rq["summary"]["unresolved_synonym_chains"] == 1
    assert rq["summary"]["domain_connectivity"] == 1
    assert rq["summary"]["total_items"] == 3


def test_review_queues_empty_when_clean():
    rq = review_queues({}, [{"domain": "media", "status": "completed", "warnings": []}])
    assert rq["summary"]["total_items"] == 0


# --- full population invariants: idempotency + resume -----------------------

def test_full_population_is_idempotent():
    orch, report1 = _full_run()
    comp1 = graph_completeness_report(orch.last_target_repo)
    orch2, report2 = _full_run()
    comp2 = graph_completeness_report(orch2.last_target_repo)
    assert report1["totals"]["edges_written"] == report2["totals"]["edges_written"]
    assert comp1["aggregate"] == comp2["aggregate"]


def test_publish_rerun_writes_nothing_new():
    repo = _taxonomy_repo()
    orch = BuildOrchestrator(repo, _source(), checkpoint_store=InMemoryCheckpointStore(),
                             batch_size=100, authorized_to_publish=True)
    first = orch.run(ExecutionMode.PUBLISH)
    assert first["totals"]["edges_written"] >= 4
    second = orch.run(ExecutionMode.PUBLISH)
    assert second["totals"]["edges_written"] == 0
    assert second["totals"]["skipped_existing_edges"] >= 4


def test_resume_skips_checkpointed_domains():
    repo = _taxonomy_repo()
    store = InMemoryCheckpointStore()
    orch = BuildOrchestrator(repo, _source(), checkpoint_store=store,
                             batch_size=100, authorized_to_publish=True)
    orch.run(ExecutionMode.PUBLISH)
    completed = store.completed_domains()
    assert completed  # domains recorded
    resumed = orch.run(ExecutionMode.RESUME)
    statuses = {o["domain"]: o["status"] for o in resumed["per_domain"]}
    for d in completed:
        assert statuses[d] == STATUS_SKIPPED


def test_completeness_stable_under_indexed_repo_scale():
    # Sanity: a larger synthetic graph produces consistent per-domain counts.
    nodes = [_taxon(i, str(i), f"Genus sp{i}") for i in range(1, 51)]
    edges = [Edge(kg_edge_id=i, edge_type="has_trait", from_node_id=i,
                  to_node_id=None, source_table="t") for i in range(1, 21)]
    repo = InMemoryGraphRepository(nodes=nodes, edges=edges)
    comp = graph_completeness_report(repo)
    assert comp["aggregate"]["total_canonical_taxa"] == 50
    assert comp["aggregate"]["taxa_connected_per_domain"]["traits"] == 20
