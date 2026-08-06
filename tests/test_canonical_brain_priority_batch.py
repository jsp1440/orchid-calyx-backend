import hashlib

import pytest

from app.canonical_brain.priority_batch import (
    ArtifactRecord,
    ArtifactRegistry,
    AtlasLayer,
    CaptureCandidate,
    DependencyScheduler,
    FigureBrief,
    KnowledgeConcept,
    LivingFigure,
    LivingFigureRegistry,
    PortfolioItem,
    ReviewGate,
    ReviewRecord,
    ScheduledBuild,
    atlas_manifest,
    brain_capture_manifest,
    orchid_root_figure_brief,
    portfolio_projection,
    recognize_terms,
    velamen_fixture,
)


def checksum(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_dependency_scheduler_is_deterministic_and_rejects_cycles() -> None:
    scheduler = DependencyScheduler()
    builds = [
        ScheduledBuild(build_id="b", priority=20, dependencies=["a"]),
        ScheduledBuild(build_id="a", priority=10),
        ScheduledBuild(build_id="c", priority=30, dependencies=["b"]),
    ]
    assert scheduler.order(builds) == ["a", "b", "c"]
    with pytest.raises(ValueError, match="cycle"):
        scheduler.order([
            ScheduledBuild(build_id="a", priority=1, dependencies=["b"]),
            ScheduledBuild(build_id="b", priority=1, dependencies=["a"]),
        ])


def test_artifact_registry_rejects_duplicate_content() -> None:
    registry = ArtifactRegistry()
    first = ArtifactRecord(
        artifact_id="artifact:1",
        media_type="image/svg+xml",
        source_uri="artifact://1.svg",
        license="CC-BY-4.0",
        producer_assignment_id="assignment:1",
        content_checksum=checksum("same"),
    )
    registry.register(first)
    with pytest.raises(ValueError, match="duplicate content"):
        registry.register(first.model_copy(update={"artifact_id": "artifact:2"}))


def test_review_gate_requires_all_classes_and_blocks_self_approval() -> None:
    with pytest.raises(ValueError, match="own artifacts"):
        ReviewRecord(
            review_id="review:1", artifact_id="artifact:1", review_class="scientific",
            reviewer_id="agent:1", producer_id="agent:1", decision="approved",
        )
    records = [
        ReviewRecord(review_id="r1", artifact_id="a", review_class="scientific", reviewer_id="human:1", producer_id="agent:1", decision="approved"),
        ReviewRecord(review_id="r2", artifact_id="a", review_class="licensing", reviewer_id="human:2", producer_id="agent:1", decision="approved"),
    ]
    assert ReviewGate().release_eligible(records, {"scientific", "licensing"})


def test_brain_capture_and_portfolio_are_repeatable() -> None:
    candidate = CaptureCandidate(build_id="BUILD-1", artifact_ids=["a"], validation_ids=["v"], source_uris=["source://1"])
    assert brain_capture_manifest(candidate) == brain_capture_manifest(candidate)
    projection = portfolio_projection([
        PortfolioItem(build_id="b", architecture_id="atlas", status="blocked", blocked_reason="review", next_action="review"),
        PortfolioItem(build_id="a", architecture_id="brain", status="running", next_action="complete"),
    ])
    assert [item["build_id"] for item in projection["items"]] == ["b", "a"]
    assert projection["write_enabled"] is False


def test_knowledge_explorer_fixture_and_term_recognition() -> None:
    concepts = velamen_fixture()
    assert {item.concept_id for item in concepts} == {"concept:velamen", "concept:exodermis", "concept:passage-cell"}
    matches = recognize_terms("The velamen lies outside the exodermis.", concepts)
    assert [item.concept_id for item in matches] == ["concept:velamen", "concept:exodermis"]
    assert all(item.review_status == "candidate" for item in concepts)


def test_figurelabs_brief_is_assisted_and_candidate_only() -> None:
    brief: FigureBrief = orchid_root_figure_brief()
    assert brief.provider == "FigureLabs-assisted"
    assert set(brief.output_formats) == {"svg", "pptx", "png"}
    assert brief.publication_status == "candidate"
    assert "velamen" in brief.required_labels


def test_atlas_manifest_requires_all_four_layer_classes() -> None:
    layers = [
        AtlasLayer(layer_id="b", category="biodiversity", dataset_uri="dataset://b", crs="EPSG:4326", checksum=checksum("b")),
        AtlasLayer(layer_id="e", category="earth_science", dataset_uri="dataset://e", crs="EPSG:4326", checksum=checksum("e")),
        AtlasLayer(layer_id="c", category="conservation", dataset_uri="dataset://c", crs="EPSG:4326", checksum=checksum("c")),
        AtlasLayer(layer_id="s", category="sampling", dataset_uri="dataset://s", crs="EPSG:4326", checksum=checksum("s")),
    ]
    first = atlas_manifest(layers)
    second = atlas_manifest(list(reversed(layers)))
    assert first == second
    assert first["publication_enabled"] is False
    with pytest.raises(ValueError, match="all four"):
        atlas_manifest(layers[:3])


def test_living_figures_require_sequential_lineage() -> None:
    registry = LivingFigureRegistry()
    first = LivingFigure(
        figure_id="figure:root", version=1, asset_ids=["asset:1"],
        concept_ids=["concept:velamen"], evidence_uris=["evidence://1"],
    )
    second = LivingFigure(
        figure_id="figure:root", version=2, supersedes_version=1, asset_ids=["asset:2"],
        concept_ids=["concept:velamen"], evidence_uris=["evidence://2"],
    )
    registry.register(first)
    registry.register(second)
    assert registry.latest("figure:root") == second
    with pytest.raises(ValueError):
        registry.register(second.model_copy(update={"version": 4, "supersedes_version": 3}))
