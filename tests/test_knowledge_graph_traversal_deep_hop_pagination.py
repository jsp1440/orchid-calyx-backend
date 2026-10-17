"""Tests for pagination behavior when deeper hops are truncated.

This module tests the pagination logic to ensure that next_offset is only
advertised when the first hop is truncated, not when deeper hops overflow.
"""

from __future__ import annotations

from runtime.knowledge_graph import (
    Edge,
    InMemoryGraphRepository,
    Node,
    traverse,
)


def _genus(nid, label, source_pk):
    return Node(nid, "genus", f"genus:{source_pk}", label,
                "public.taxonomy_genus", str(source_pk), "curated", 1.0, "high")


def _species(nid, label, source_pk):
    return Node(nid, "taxon", f"taxon:{source_pk}", label,
                "public.taxonomy_species", str(source_pk), "curated", 1.0, "high")


def _image(nid, image_id):
    return Node(nid, "image", f"image:{image_id}", f"Image {image_id}",
                "oc_core.media_assets", str(image_id), "harvested", 0.8, "medium")


def _edge(eid, etype, frm, to):
    return Edge(eid, etype, frm, to, "public.taxonomy_species", str(to),
                "curated", 1.0, "high", "taxonomy_rule")


def test_deep_hop_truncation_no_next_offset():
    """Test that truncation at deeper hops does not set next_offset.

    Graph: genus -> 1 species -> 3 images
    Query: depth=2, limit=2

    The species hop has 1 edge (no truncation).
    The image hop would have 3 edges, but we only fetch 2 (truncated).
    Result: truncated=True but next_offset should be None because
    the first hop (genus->species) was not truncated.
    """
    nodes = [
        _genus(1, "Genus A", 560),
        _species(2, "Species A", "a b"),
        _image(10, 0),
        _image(11, 1),
        _image(12, 2),
    ]
    edges = [
        _edge(1, "genus_contains_species", 1, 2),
        Edge(10, "has_image", 2, 10, "oc_core.media_assets", "0",
             "harvested", 0.8, "medium", "media_rule"),
        Edge(11, "has_image", 2, 11, "oc_core.media_assets", "1",
             "harvested", 0.8, "medium", "media_rule"),
        Edge(12, "has_image", 2, 12, "oc_core.media_assets", "2",
             "harvested", 0.8, "medium", "media_rule"),
    ]
    repo = InMemoryGraphRepository(nodes, edges)
    focal = repo.find_genus_node("Genus A")

    result = traverse(repo, focal, depth=2, limit=2)

    # The result should show truncation at the image level
    assert result["pagination"]["truncated"] is True
    # But next_offset should be None because first hop was not truncated
    assert result["pagination"]["next_offset"] is None
    # We should have fetched 1 species and 2 images (limited by limit=2 at image hop)
    assert result["graph"]["node_count"] == 3  # 1 species + 2 images


def test_first_hop_truncation_sets_next_offset():
    """Test that truncation at the first hop properly sets next_offset.

    Graph: genus -> 5 species (limited to 2)
    Query: depth=1, limit=2

    Result: truncated=True and next_offset=2 because the first (and only) hop
    is truncated.
    """
    nodes = [_genus(1, "Genus A", 560)]
    edges = []
    for i in range(5):
        nid = 2 + i
        nodes.append(_species(nid, f"Species {i}", f"sp{i}"))
        edges.append(_edge(i + 1, "genus_contains_species", 1, nid))

    repo = InMemoryGraphRepository(nodes, edges)
    focal = repo.find_genus_node("Genus A")

    result = traverse(repo, focal, depth=1, limit=2)

    assert result["pagination"]["truncated"] is True
    assert result["pagination"]["next_offset"] == 2
    assert result["graph"]["node_count"] == 2


def test_first_hop_with_offset_continuation():
    """Test that pagination continuation at first hop works correctly.

    Graph: genus -> 5 species
    Query: depth=1, limit=2, offset=2

    Result: truncated=True and next_offset=4 to continue pagination.
    """
    nodes = [_genus(1, "Genus A", 560)]
    edges = []
    for i in range(5):
        nid = 2 + i
        nodes.append(_species(nid, f"Species {i}", f"sp{i}"))
        edges.append(_edge(i + 1, "genus_contains_species", 1, nid))

    repo = InMemoryGraphRepository(nodes, edges)
    focal = repo.find_genus_node("Genus A")

    result = traverse(repo, focal, depth=1, limit=2, offset=2)

    assert result["pagination"]["truncated"] is True
    assert result["pagination"]["next_offset"] == 4
    assert result["graph"]["node_count"] == 2


def test_no_truncation_no_next_offset():
    """Test that when there is no truncation, next_offset is None.

    Graph: genus -> 2 species
    Query: depth=1, limit=5

    Result: truncated=False and next_offset=None.
    """
    nodes = [_genus(1, "Genus A", 560)]
    edges = []
    for i in range(2):
        nid = 2 + i
        nodes.append(_species(nid, f"Species {i}", f"sp{i}"))
        edges.append(_edge(i + 1, "genus_contains_species", 1, nid))

    repo = InMemoryGraphRepository(nodes, edges)
    focal = repo.find_genus_node("Genus A")

    result = traverse(repo, focal, depth=1, limit=5)

    assert result["pagination"]["truncated"] is False
    assert result["pagination"]["next_offset"] is None
    assert result["graph"]["node_count"] == 2
