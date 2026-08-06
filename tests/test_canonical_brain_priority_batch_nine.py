from datetime import datetime, timezone

import pytest

from app.canonical_brain.priority_batch_nine import (
    DatasetLineageNode,
    DependencyEdge,
    FigureLabel,
    GlossaryEditorialItem,
    IntegrationMetric,
    LocationMove,
    LocationMoveLedger,
    ParentProfile,
    ReleaseArtifact,
    RoadmapBuild,
    ThreatObservation,
    assess_glossary_editorial_readiness,
    assess_hybrid_ambiguity,
    audit_roadmap_consistency,
    build_dataset_lineage_manifest,
    build_dependency_heatmap,
    build_publication_release_packet,
    build_threat_overlay,
    summarize_integration_health,
    validate_scientific_figure,
)


def test_glossary_editorial_gaps_are_explicit():
    item = GlossaryEditorialItem(concept_id="velamen", definition="Short", evidence_ids=["ev:1"])
    assert assess_glossary_editorial_readiness(item) == [
        "definition_too_short",
        "missing_media",
        "editorial_review_pending",
    ]


def test_threat_overlay_is_deterministic_and_evidence_linked():
    observations = [
        ThreatObservation(cell_id="c1", threat_type="fire", severity=0.8, confidence=0.5, evidence_id="e2"),
        ThreatObservation(cell_id="c1", threat_type="land_use", severity=0.4, confidence=1.0, evidence_id="e1"),
    ]
    first = build_threat_overlay(observations)
    second = build_threat_overlay(list(reversed(observations)))
    assert first == second
    assert first[0].evidence_ids == ["e1", "e2"]


def test_dataset_lineage_rejects_cycles_and_orders_parents_first():
    checksum = "a" * 64
    nodes = [
        DatasetLineageNode(dataset_id="raw", checksum=checksum, transformation="ingest", source_uri="s3://raw"),
        DatasetLineageNode(dataset_id="clean", checksum=checksum, parent_dataset_ids=["raw"], transformation="clean", source_uri="s3://clean"),
    ]
    assert build_dataset_lineage_manifest(nodes).ordered_dataset_ids == ["raw", "clean"]
    cyclic = [
        DatasetLineageNode(dataset_id="a", checksum=checksum, parent_dataset_ids=["b"], transformation="x", source_uri="u:a"),
        DatasetLineageNode(dataset_id="b", checksum=checksum, parent_dataset_ids=["a"], transformation="x", source_uri="u:b"),
    ]
    with pytest.raises(ValueError, match="cycle"):
        build_dataset_lineage_manifest(cyclic)


def test_location_move_is_idempotent_and_rejects_noop():
    ledger = LocationMoveLedger()
    move = LocationMove(
        move_id="move:1",
        specimen_id="spec:1",
        from_location="bench-a",
        to_location="bench-b",
        moved_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        reason="increase light",
    )
    assert ledger.register(move) == ledger.register(move)
    with pytest.raises(ValueError, match="different destination"):
        ledger.register(move.model_copy(update={"move_id": "move:2", "to_location": "bench-a"}))


def test_hybrid_ambiguity_separates_parent_matches():
    result = assess_hybrid_ambiguity(
        "obs:1",
        {"lip": "red", "spur": "long", "leaf": "thick"},
        ParentProfile(taxon_id="a", states={"lip": "red", "spur": "short", "leaf": "thin"}),
        ParentProfile(taxon_id="b", states={"lip": "white", "spur": "long", "leaf": "thin"}),
    )
    assert result.parent_a_matches == 1
    assert result.parent_b_matches == 1
    assert result.ambiguous_character_ids == ["leaf"]


def test_figure_validation_requires_complete_labels():
    result = validate_scientific_figure(
        "fig:1",
        ["r1", "r2"],
        [FigureLabel(label_id="l1", text="velamen", target_region_id="r1", evidence_id="ev:1")],
    )
    assert result.unlabeled_region_ids == ["r2"]
    assert result.ready_for_review is False


def test_release_packet_never_enables_release():
    packet = build_publication_release_packet(
        "packet:1",
        [ReleaseArtifact(artifact_id="a1", checksum="b" * 64, license="CC-BY-4.0")],
        ["scientific", "licensing"],
        ["scientific"],
    )
    assert packet.release_enabled is False
    assert packet.required_review_classes == ["licensing", "scientific"]


def test_integration_health_rejects_inconsistent_counts():
    with pytest.raises(ValueError, match="attempt counts"):
        summarize_integration_health(IntegrationMetric(contract_id="c", attempted=3, succeeded=1, failed=1, dead_lettered=0))


def test_dependency_heatmap_rejects_self_edges_and_ranks_hot_nodes():
    heat = build_dependency_heatmap([
        DependencyEdge(source_id="brain", target_id="atlas"),
        DependencyEdge(source_id="brain", target_id="matrix"),
    ])
    assert heat[0].object_id == "brain"
    with pytest.raises(ValueError, match="self dependencies"):
        build_dependency_heatmap([DependencyEdge(source_id="brain", target_id="brain")])


def test_roadmap_audit_detects_missing_and_premature_completion():
    report = audit_roadmap_consistency([
        RoadmapBuild(build_id="a", priority=1, status="active"),
        RoadmapBuild(build_id="b", priority=2, dependency_ids=["a", "missing"], status="completed"),
    ])
    assert report.missing_dependency_ids == ["missing"]
    assert report.completed_before_dependency_ids == ["b"]
    assert report.consistent is False
