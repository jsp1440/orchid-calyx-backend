"""Regression tests for the scientific Knowledge Graph package.

Every test runs against an in-memory repository — no database connection is
ever opened, guaranteeing "no production writes during tests".  The Cattleya /
Bulbophyllum / Dracula fixtures are synthetic and prove the traversal is
generic, not hard-coded per genus.
"""

from __future__ import annotations

import pytest

from runtime.knowledge_graph import (
    DomainAdapter,
    Edge,
    EdgeSpec,
    InMemoryGraphRepository,
    Node,
    NodeSpec,
    canonical_key,
    publish_domain,
    quality_report,
    traverse,
)
from runtime.knowledge_graph.vocabulary import ALL_DOMAINS


def _genus(nid, label, source_pk):
    return Node(nid, "genus", canonical_key("genus", source_pk), label,
                "public.taxonomy_genus", str(source_pk), "curated", 1.0, "high")


def _species(nid, label, source_pk):
    return Node(nid, "taxon", canonical_key("taxon", source_pk), label,
                "public.taxonomy_species", str(source_pk), "curated", 1.0, "high")


def _edge(eid, etype, frm, to):
    return Edge(eid, etype, frm, to, "public.taxonomy_species", str(to),
                "curated", 1.0, "high", "taxonomy_rule")


def build_taxonomy_repo(genus_label, genus_pk, species):
    nodes = [_genus(1, genus_label, genus_pk)]
    edges = []
    eid = 1
    for i, (label, pk) in enumerate(species, start=2):
        nodes.append(_species(i, label, pk))
        edges.append(_edge(eid, "genus_contains_species", 1, i)); eid += 1
        edges.append(_edge(eid, "species_belongs_to_genus", i, 1)); eid += 1
    return InMemoryGraphRepository(nodes, edges)


# ---- traversal ----

def test_genus_traversal_returns_species_and_gaps():
    repo = build_taxonomy_repo("Cattleya", 560, [
        ("Cattleya labiata", 1001), ("Cattleya aclandiae", 1002),
        ("Cattleya aracuaiensis", 1003),
    ])
    focal = repo.find_genus_node("Cattleya")
    result = traverse(repo, focal, depth=1)
    assert result["focal_node"]["label"] == "Cattleya"
    species = [n for n in result["nodes"] if n["node_type"] == "taxon"]
    assert len(species) == 3
    assert "taxonomy" in result["domain_coverage"]
    # every non-taxonomy domain is an explicit gap given a taxonomy-only graph
    for domain in ALL_DOMAINS:
        if domain != "taxonomy":
            assert domain in result["data_gaps"]


def test_case_insensitive_genus_lookup():
    repo = build_taxonomy_repo("Bulbophyllum", 99, [("Bulbophyllum medusae", 2001)])
    assert repo.find_genus_node("bulbophyllum") is not None
    assert repo.find_genus_node("BULBOPHYLLUM") is not None


def test_node_type_filter():
    repo = build_taxonomy_repo("Dracula", 77, [("Dracula vampira", 3001)])
    focal = repo.find_genus_node("Dracula")
    result = traverse(repo, focal, depth=1, node_types=["publication"])
    assert result["nodes"] == []  # no publication nodes present


def test_edge_type_filter():
    repo = build_taxonomy_repo("Cattleya", 560, [("Cattleya labiata", 1001)])
    focal = repo.find_genus_node("Cattleya")
    result = traverse(repo, focal, depth=1, edge_types=["genus_contains_species"])
    assert result["edge_types"] == ["genus_contains_species"]


def test_pagination_limit_and_truncation():
    repo = build_taxonomy_repo("Cattleya", 560, [(f"Cattleya sp{i}", 4000 + i) for i in range(5)])
    focal = repo.find_genus_node("Cattleya")
    result = traverse(repo, focal, depth=1, edge_types=["genus_contains_species"], limit=2)
    assert result["pagination"]["truncated"] is True
    assert result["pagination"]["next_offset"] == 2
    assert len(result["edges"]) == 2


def test_depth_is_clamped():
    repo = build_taxonomy_repo("Cattleya", 560, [("Cattleya labiata", 1001)])
    focal = repo.find_genus_node("Cattleya")
    result = traverse(repo, focal, depth=99)
    assert result["graph"]["depth"] <= 3


def test_dangling_edge_omitted_from_traversal():
    nodes = [_genus(1, "Cattleya", 560)]
    edges = [_edge(1, "genus_contains_species", 1, 999)]  # 999 does not exist
    repo = InMemoryGraphRepository(nodes, edges)
    focal = repo.find_genus_node("Cattleya")
    result = traverse(repo, focal, depth=1)
    assert result["nodes"] == []


# ---- publisher (idempotency, provenance, evidence, dedup) ----

def _media_adapter():
    def produce(rows):
        nodes, edges = [], []
        for r in rows:
            nodes.append(NodeSpec("image", r["image_id"], r.get("caption"),
                                  "oc_core.media_assets", "harvested",
                                  r.get("confidence", 0.8), "medium",
                                  {"url": r.get("url")}))
            edges.append(EdgeSpec("has_image", canonical_key("taxon", r["taxon_pk"]),
                                  canonical_key("image", r["image_id"]),
                                  "oc_core.record_media_link", r["image_id"],
                                  "harvested", r.get("confidence", 0.8), "medium",
                                  "media_link_rule"))
        return nodes, edges
    return DomainAdapter("media", "oc_core.media_assets", produce)


def _repo_with_species():
    return InMemoryGraphRepository([_species(10, "Cattleya labiata", 1001)], [])


def test_publish_creates_nodes_and_edges():
    repo = _repo_with_species()
    rows = [{"image_id": 5001, "taxon_pk": 1001, "url": "u1", "caption": "flower"}]
    res = publish_domain(repo, _media_adapter(), rows)
    assert res.nodes_written == 1 and res.edges_written == 1
    img = repo.get_node_by_key(canonical_key("image", 5001))
    assert img.source_table == "oc_core.media_assets"      # provenance preserved
    assert img.payload["url"] == "u1"


def test_publish_is_idempotent():
    repo = _repo_with_species()
    rows = [{"image_id": 5001, "taxon_pk": 1001, "url": "u1"}]
    publish_domain(repo, _media_adapter(), rows)
    res2 = publish_domain(repo, _media_adapter(), rows)  # rebuild
    assert res2.nodes_written == 0 and res2.edges_written == 0
    assert res2.skipped_existing_nodes == 1 and res2.skipped_existing_edges == 1
    images = [n for n in repo.all_nodes() if n.node_type == "image"]
    assert len(images) == 1  # no duplicate canonical node


def test_publish_rejects_unknown_vocabulary():
    repo = _repo_with_species()
    def produce(rows):
        return [NodeSpec("not_a_type", 1, "x", "t")], []
    res = publish_domain(repo, DomainAdapter("x", "t", produce), [{}])
    assert any("node_type:not_a_type" in i for i in res.invalid)
    assert res.nodes_written == 0


def test_evidence_and_confidence_preserved_on_edge():
    repo = _repo_with_species()
    rows = [{"image_id": 5001, "taxon_pk": 1001, "confidence": 0.42}]
    publish_domain(repo, _media_adapter(), rows)
    edge = repo.all_edges()[0]
    assert edge.evidence_class == "harvested"
    assert edge.confidence_score == 0.42


# ---- quality ----

def test_quality_flags_dangling_and_orphans():
    nodes = [_genus(1, "Cattleya", 560), _species(2, "orphan sp", 1001)]
    edges = [_edge(1, "genus_contains_species", 1, 999)]  # dangling
    repo = InMemoryGraphRepository(nodes, edges)
    q = quality_report(repo)
    assert q["dangling_edges"] == 1
    assert q["orphan_nodes"] >= 1
    assert q["healthy"] is False


def test_quality_healthy_graph():
    repo = build_taxonomy_repo("Cattleya", 560, [("Cattleya labiata", 1001)])
    q = quality_report(repo)
    assert q["dangling_edges"] == 0
    assert q["duplicate_canonical_nodes"] == 0
    assert q["healthy"] is True


def test_quality_detects_duplicate_canonical_nodes():
    nodes = [_genus(1, "Cattleya", 560), _genus(2, "Cattleya dup", 560)]
    repo = InMemoryGraphRepository(nodes, [])
    q = quality_report(repo)
    assert q["duplicate_canonical_nodes"] == 1


# ---- multi-genus proof: same code path, different taxa ----

@pytest.mark.parametrize("genus,pk,species", [
    ("Cattleya", 560, [("Cattleya labiata", 1), ("Cattleya aclandiae", 2), ("Cattleya walkeriana", 3)]),
    ("Bulbophyllum", 99, [("Bulbophyllum medusae", 4), ("Bulbophyllum lobbii", 5), ("Bulbophyllum falcatum", 6)]),
    ("Dracula", 77, [("Dracula vampira", 7), ("Dracula simia", 8), ("Dracula bella", 9)]),
])
def test_multi_genus_traversal_generic(genus, pk, species):
    repo = build_taxonomy_repo(genus, pk, species)
    focal = repo.find_genus_node(genus)
    result = traverse(repo, focal, depth=1)
    assert len(result["nodes"]) == 3
    assert result["focal_node"]["node_type"] == "genus"
