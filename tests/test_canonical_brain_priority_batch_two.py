from app.canonical_brain.priority_batch_two import (
    CharacterState,
    EarthSystemsAdapter,
    MatrixTaxon,
    PublicationPackage,
    PublicationSection,
    ResearchWorkspace,
    SpatialLayerRecord,
    SpatialLayerRegistry,
    SpecimenRecord,
    VisualObservation,
    build_readiness_projection,
    checksum,
    compare_taxa,
    make_event,
    render_thematic_map,
)


def layer(layer_id: str, category: str) -> SpatialLayerRecord:
    return SpatialLayerRecord(
        layer_id=layer_id,
        dataset_id=f"dataset:{layer_id}",
        category=category,
        crs="EPSG:4326",
        source_uri=f"https://example.org/{layer_id}",
        license_id="CC-BY-4.0",
        content_checksum=checksum(layer_id),
    )


def test_spatial_registry_and_renderer_are_deterministic() -> None:
    registry = SpatialLayerRegistry()
    layers = [
        layer("sampling", "sampling"),
        layer("elevation", "earth-science"),
        layer("orchids", "biodiversity"),
        layer("protected", "conservation"),
    ]
    for item in layers:
        registry.register(item)
    first = render_thematic_map("map:1", registry.snapshot(), "svg")
    second = render_thematic_map("map:1", list(reversed(registry.snapshot())), "svg")
    assert first == second
    assert first.publication_enabled is False


def test_earth_adapter_rejects_unsupported_variable() -> None:
    adapter = EarthSystemsAdapter("WorldClim", {"temperature", "precipitation"})
    candidate = adapter.normalize("temperature", "2.1", "https://example.org/worldclim", "CC-BY-4.0")
    assert candidate.dataset_id.startswith("earth:worldclim")
    try:
        adapter.normalize("geology", "1", "https://example.org", "CC-BY")
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsupported variable should fail")


def test_research_workspace_remains_candidate_only() -> None:
    workspace = ResearchWorkspace(workspace_id="rs:1", hypothesis="Velamen thickness relates to habitat.", evidence=[])
    assert workspace.conclusion_ready() is False
    assert workspace.publication_enabled is False


def test_specimen_generates_stable_qr_and_label() -> None:
    specimen = SpecimenRecord(
        specimen_id="specimen:1",
        accession_number="FCOS-0001",
        taxon_name="Laelia anceps",
        location_code="GH-A1",
        provenance_uri="https://example.org/source",
    )
    assert specimen.qr_payload.endswith("specimen:1")
    assert "FCOS-0001" in specimen.label_text


def test_matrix_reports_matches_differences_and_missing() -> None:
    left = MatrixTaxon(taxon_id="a", states=[CharacterState(character_id="c1", label="color", value="red"), CharacterState(character_id="c2", label="size", value=None)])
    right = MatrixTaxon(taxon_id="b", states=[CharacterState(character_id="c1", label="color", value="blue"), CharacterState(character_id="c2", label="size", value=2)])
    result = compare_taxa(left, right)
    assert result["differences"] == ["c1"]
    assert result["missing"] == ["c2"]


def test_visual_observation_requires_review_for_publication() -> None:
    candidate = VisualObservation(
        observation_id="obs:1",
        asset_uri="https://example.org/image.jpg",
        region=(0.1, 0.1, 0.5, 0.5),
        proposed_character_id="character:velamen",
        proposed_value="present",
        confidence=0.92,
    )
    assert candidate.is_publishable() is False
    assert candidate.model_copy(update={"status": "reviewed"}).is_publishable() is True


def test_publication_package_does_not_auto_publish() -> None:
    package = PublicationPackage(
        package_id="pub:1",
        title="Velamen overview",
        sections=[PublicationSection(heading="Evidence", text="Candidate synthesis.", evidence_ids=["e:1"])],
        review_status="approved",
    )
    assert package.publication_enabled is False


def test_event_and_readiness_projection_are_stable() -> None:
    first = make_event("artifact.created", "atlas", "map:1", {"a": 1})
    second = make_event("artifact.created", "atlas", "map:1", {"a": 1})
    assert first == second
    projection = build_readiness_projection(
        {"brain": "ready", "atlas": "ready", "publishing": "blocked"},
        {"publishing": ["brain", "atlas"], "atlas": ["brain"]},
    )
    assert projection.ready_count == 2
    assert projection.blocked_subsystems == []
