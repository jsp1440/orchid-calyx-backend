"""Regression tests for runtime.knowledge_graph.analytics — the GRAPH-001A
first analytical increment (bounded snapshot, connected components, degree,
shortest path, reproducibility metadata).

Every test runs against an in-memory repository — no database connection is
ever opened. The Dracula / Bulbophyllum fixtures are synthetic orchid-domain
data mirroring the existing traversal test fixtures' style.
"""
from __future__ import annotations

from runtime.knowledge_graph import (
    Edge,
    InMemoryGraphRepository,
    Node,
    canonical_key,
)
from runtime.knowledge_graph.analytics import (
    ANALYTICS_ENGINE_VERSION,
    bounded_snapshot,
    connected_components,
    degree,
    shortest_path,
)


def _genus(nid, label, source_pk):
    return Node(
        nid, "genus", canonical_key("genus", source_pk), label,
        "public.taxonomy_genus", str(source_pk), "curated", 1.0, "high",
    )


def _species(nid, label, source_pk):
    return Node(
        nid, "taxon", canonical_key("taxon", source_pk), label,
        "public.taxonomy_species", str(source_pk), "curated", 1.0, "high",
    )


def _pollinator(nid, label, source_pk):
    return Node(
        nid, "pollinator", canonical_key("pollinator", source_pk), label,
        "public.pollinator_observations", str(source_pk), "observed", 0.6, "moderate",
    )


def _edge(eid, etype, frm, to, *, confidence=1.0, label="high"):
    return Edge(
        eid, etype, frm, to, "public.taxonomy_species", str(to),
        "curated", confidence, label, "taxonomy_rule",
    )


def build_dracula_repo():
    """One connected tree: Dracula (genus) -> D. vampira (species) ->
    Diptera sp. (pollinator), plus a reciprocal species->genus edge - the
    same bidirectional pattern the existing traversal fixtures use."""
    genus = _genus(1, "Dracula", 700)
    species = _species(2, "Dracula vampira", 2001)
    pollinator = _pollinator(3, "Diptera sp.", 9001)
    nodes = [genus, species, pollinator]
    edges = [
        _edge(1, "genus_contains_species", 1, 2),
        _edge(2, "species_belongs_to_genus", 2, 1),
        _edge(3, "associated_with_pollinator", 2, 3, confidence=0.6, label="moderate"),
    ]
    return InMemoryGraphRepository(nodes, edges), genus, species, pollinator


def test_bounded_snapshot_includes_focal_node_and_reproducibility_metadata():
    repo, genus, _species, _pollinator = build_dracula_repo()
    snapshot = bounded_snapshot(repo, genus, depth=2)

    node_ids = {n["id"] for n in snapshot["nodes"]}
    assert genus.kg_node_id in node_ids  # focal node included, unlike raw traverse()
    assert {2, 3} <= node_ids

    repro = snapshot["reproducibility"]
    assert repro["algorithm"] == "bounded_snapshot"
    assert repro["engine_version"] == ANALYTICS_ENGINE_VERSION
    assert repro["scope"]["focal_node_id"] == 1
    assert repro["scope"]["focal_canonical_key"] == genus.canonical_key
    assert "computed_at" in repro
    assert isinstance(repro["warnings"], list)
    assert len(repro["limitations"]) >= 2


def test_bounded_snapshot_flags_truncation_in_warnings():
    repo, genus, _species, _pollinator = build_dracula_repo()
    snapshot = bounded_snapshot(repo, genus, depth=2, limit=1)

    assert snapshot["pagination"]["truncated"] is True
    assert any("truncat" in w.lower() for w in snapshot["reproducibility"]["warnings"])


def test_connected_components_end_to_end_through_bounded_snapshot():
    repo, genus, _species, _pollinator = build_dracula_repo()
    snapshot = bounded_snapshot(repo, genus, depth=2)
    result = connected_components(snapshot)

    assert result["component_count"] == 1
    assert result["largest_component_size"] == 3
    assert result["components"] == [[1, 2, 3]]
    assert result["reproducibility"]["algorithm"] == "connected_components"


def test_connected_components_separates_disjoint_subgraphs():
    """A snapshot built directly (not via one traverse() call, which by
    construction can only return one connected component from its focal
    node) proves the algorithm itself correctly separates unconnected
    groups rather than merging everything into one component by default."""
    snapshot = {
        "nodes": [{"id": i} for i in (1, 2, 3, 10, 11)],
        "edges": [
            {"from": 1, "to": 2, "confidence": {"score": 1.0}},
            {"from": 2, "to": 3, "confidence": {"score": 1.0}},
            {"from": 10, "to": 11, "confidence": {"score": 1.0}},
        ],
        "reproducibility": {"scope": {"focal_node_id": None}},
    }
    result = connected_components(snapshot)

    assert result["component_count"] == 2
    assert result["largest_component_size"] == 3
    assert sorted(result["components"]) == [[1, 2, 3], [10, 11]]


def test_degree_unweighted_counts_edges_per_node():
    repo, genus, _species, _pollinator = build_dracula_repo()
    snapshot = bounded_snapshot(repo, genus, depth=2)
    result = degree(snapshot)

    assert result["weighted"] is False
    assert result["by_node"][1] == {"in_degree": 1, "out_degree": 1, "total_degree": 2}
    assert result["by_node"][2] == {"in_degree": 1, "out_degree": 2, "total_degree": 3}
    assert result["by_node"][3] == {"in_degree": 1, "out_degree": 0, "total_degree": 1}


def test_degree_weighted_sums_confidence_scores_and_defaults_missing_to_one():
    snapshot = {
        "nodes": [{"id": 1}, {"id": 2}],
        "edges": [
            {"from": 1, "to": 2, "confidence": {"score": 0.4}},
            {"from": 1, "to": 2, "confidence": {}},  # missing score -> defaults to 1.0
        ],
        "reproducibility": {"scope": {}},
    }
    result = degree(snapshot, weighted=True)

    assert result["weighted"] is True
    assert result["by_node"][1]["out_weighted_degree"] == 1.4
    assert result["by_node"][2]["in_weighted_degree"] == 1.4
    assert result["by_node"][1]["out_degree"] == 2  # unweighted count still present


def test_shortest_path_finds_fewest_hops_not_confidence_weighted():
    repo, genus, _species, _pollinator = build_dracula_repo()
    snapshot = bounded_snapshot(repo, genus, depth=2)
    result = shortest_path(snapshot, source_id=1, target_id=3)

    assert result["found"] is True
    assert result["path"] == [1, 2, 3]
    assert result["hop_count"] == 2
    assert result["reproducibility"]["algorithm"] == "shortest_path_bfs_directed"


def test_shortest_path_reports_not_found_without_raising():
    snapshot = {
        "nodes": [{"id": 1}, {"id": 2}, {"id": 10}, {"id": 11}],
        "edges": [
            {"from": 1, "to": 2, "confidence": {}},
            {"from": 10, "to": 11, "confidence": {}},
        ],
        "reproducibility": {"scope": {}},
    }
    result = shortest_path(snapshot, source_id=1, target_id=11)

    assert result["found"] is False
    assert result["path"] == []
    assert result["hop_count"] is None


def test_shortest_path_warns_when_endpoint_outside_snapshot():
    snapshot = {
        "nodes": [{"id": 1}, {"id": 2}],
        "edges": [{"from": 1, "to": 2, "confidence": {}}],
        "reproducibility": {"scope": {}},
    }
    result = shortest_path(snapshot, source_id=1, target_id=999)

    assert result["found"] is False
    assert any("not present in this bounded snapshot" in w for w in result["reproducibility"]["warnings"])


def test_second_orchid_domain_fixture_stays_isolated_from_the_first():
    """Bulbophyllum fixture, entirely separate node-id space from the
    Dracula fixture, proves nothing in the module hardcodes assumptions
    about a single global graph shape."""
    genus = _genus(101, "Bulbophyllum", 800)
    species = _species(102, "Bulbophyllum echinolabium", 3001)
    pollinator = _pollinator(103, "Calliphoridae sp.", 9002)
    repo = InMemoryGraphRepository(
        [genus, species, pollinator],
        [
            _edge(1, "genus_contains_species", 101, 102),
            _edge(2, "species_belongs_to_genus", 102, 101),
            _edge(3, "associated_with_pollinator", 102, 103, confidence=0.9, label="high"),
        ],
    )
    snapshot = bounded_snapshot(repo, genus, depth=2)
    components = connected_components(snapshot)
    path = shortest_path(snapshot, source_id=101, target_id=103)

    assert components["component_count"] == 1
    assert path["found"] is True
    assert path["hop_count"] == 2
