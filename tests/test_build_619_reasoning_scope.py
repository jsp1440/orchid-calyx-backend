from __future__ import annotations

from app.brain.reasoning_scope import evaluate_scope
from app.brain.scoped_reasoning_map import (
    ScopedReasoningMapRequest,
    build_scoped_reasoning_map,
)
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def node(node_id, node_type, key, label):
    return Node(node_id, node_type, key, label)


def edge(edge_id, source, target, scope):
    return Edge(
        edge_id,
        "promotes",
        source,
        target,
        evidence_class="published_mechanistic_claim",
        confidence_score=0.9,
        payload={"causal_scope": scope},
    )


def test_matching_bounded_scope_is_applicable():
    result = evaluate_scope(
        {
            "scope_class": "bounded",
            "taxa": ["Phalaenopsis"],
            "tissues": ["leaf"],
        },
        {
            "scope_class": "bounded",
            "taxa": ["phalaenopsis"],
            "tissues": ["leaf"],
        },
    )
    assert result["status"] == "applicable"
    assert result["applicable"] is True


def test_nonmatching_tissue_is_out_of_scope():
    result = evaluate_scope(
        {"scope_class": "bounded", "tissues": ["root"]},
        {"scope_class": "bounded", "tissues": ["leaf"]},
    )
    assert result["status"] == "out_of_scope"
    assert result["mismatched_dimensions"] == ["tissues"]


def test_missing_requested_dimension_is_indeterminate_not_match():
    result = evaluate_scope(
        {"scope_class": "bounded", "environments": {"temperature_c": 16}},
        {"scope_class": "bounded", "environments": {"humidity_percent": 80}},
    )
    assert result["status"] == "indeterminate"
    assert result["unresolved_dimensions"] == ["environments"]


def test_unknown_claim_scope_is_indeterminate():
    result = evaluate_scope(
        {"scope_class": "unknown"},
        {"scope_class": "bounded", "taxa": ["cattleya"]},
    )
    assert result["status"] == "indeterminate"
    assert "claim_scope_unknown" in result["unresolved_dimensions"]


def test_scoped_reasoning_map_retains_out_of_scope_paths_transparently():
    repo = InMemoryGraphRepository(
        [
            node(1, "environment", "environment:cool", "Cool nights"),
            node(2, "physiology", "physiology:respiration", "Respiration"),
            node(3, "phenotype", "phenotype:growth", "Growth"),
        ],
        [
            edge(10, 1, 2, {"scope_class": "bounded", "tissues": ["root"]}),
            edge(11, 2, 3, {"scope_class": "bounded", "tissues": ["root"]}),
        ],
    )
    request = ScopedReasoningMapRequest.model_validate(
        {
            "subject_node_id": 1,
            "applicability_scope": {
                "scope_class": "bounded",
                "tissues": ["leaf"],
            },
            "causal_only": True,
        }
    )
    result = build_scoped_reasoning_map(repo, request)
    assert result["scope_summary"]["out_of_scope_path_count"] > 0
    assert result["scope_summary"]["safe_to_generalize"] is False
    assert any(
        path["applicability"]["status"] == "out_of_scope" for path in result["paths"]
    )
    assert (
        result["governance"]["out_of_scope_paths_are_retained_for_transparency"] is True
    )


def test_empty_reasoning_map_is_not_safe_to_generalize():
    repo = InMemoryGraphRepository(
        [node(1, "environment", "environment:cool", "Cool nights")],
        [],
    )
    request = ScopedReasoningMapRequest.model_validate(
        {
            "subject_node_id": 1,
            "applicability_scope": {
                "scope_class": "bounded",
                "tissues": ["leaf"],
            },
        }
    )
    result = build_scoped_reasoning_map(repo, request)
    assert result["paths"] == []
    assert result["scope_summary"]["safe_to_generalize"] is False


def test_global_claim_scope_applies_to_bounded_query():
    result = evaluate_scope(
        {
            "scope_class": "global",
            "global_justification": "Supported across tested orchid lineages.",
        },
        {
            "scope_class": "bounded",
            "taxa": ["cattleya"],
            "tissues": ["leaf"],
        },
    )
    assert result["status"] == "applicable"
    assert result["matched_dimensions"] == ["global"]
