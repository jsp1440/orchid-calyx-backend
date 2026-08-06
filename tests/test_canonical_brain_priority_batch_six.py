from datetime import datetime, timezone

import pytest

from app.canonical_brain.priority_batch_six import (
    ArchitectureFingerprint,
    BloomHistory,
    BloomRecord,
    CalibrationObservation,
    CriticalPathBuild,
    EventSchema,
    GlossaryMediaCandidate,
    GrantSection,
    HerbariumInterpretation,
    NotebookCell,
    SamplingCell,
    assemble_grant_package,
    assess_schema_compatibility,
    build_provenance_notebook,
    calculate_critical_path,
    calibrate_confidence,
    detect_duplicate_architectures,
    rank_sampling_gaps,
    select_glossary_media,
    validate_herbarium_interpretation,
)


def test_glossary_media_selection_is_accessible_and_deterministic() -> None:
    items = [
        GlossaryMediaCandidate(asset_id="photo", media_type="photograph", evidence_ids=["e1"], alt_text="Root surface photograph", license="CC-BY", relevance_score=0.9, accessibility_score=0.8),
        GlossaryMediaCandidate(asset_id="diagram", media_type="diagram", evidence_ids=["e2"], alt_text="Layered root diagram", license="CC-BY", relevance_score=0.8, accessibility_score=1.0),
    ]
    first = select_glossary_media("velamen", items)
    second = select_glossary_media("velamen", list(reversed(items)))
    assert first == second
    assert first.selected_asset_ids == ["diagram", "photo"]


def test_sampling_gap_ranking_favors_suitable_under_sampled_cells() -> None:
    result = rank_sampling_gaps([
        SamplingCell(cell_id="well-sampled", occurrence_count=20, effort_score=0.9, suitability_score=0.9, evidence_ids=["e1"]),
        SamplingCell(cell_id="gap", occurrence_count=0, effort_score=0.1, suitability_score=0.8, evidence_ids=["e2"]),
    ])
    assert result[0].cell_id == "gap"
    assert result[0].status == "candidate"


def test_provenance_notebook_is_repeatable_and_execution_disabled() -> None:
    checksum = "a" * 64
    cells = [NotebookCell(cell_id="2", cell_type="markdown", source_checksum=checksum), NotebookCell(cell_id="1", cell_type="code", source_checksum=checksum)]
    notebook = build_provenance_notebook("nb-1", "b" * 64, cells)
    assert [item.cell_id for item in notebook.cells] == ["1", "2"]
    assert notebook.execution_enabled is False


def test_bloom_history_rejects_invalid_dates_and_conflicts() -> None:
    history = BloomHistory()
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = BloomRecord(bloom_id="b1", specimen_id="s1", opened_at=opened)
    history.register(record)
    assert history.for_specimen("s1") == [record]
    with pytest.raises(ValueError):
        history.register(record.model_copy(update={"notes": "changed"}))
    with pytest.raises(ValueError):
        history.register(BloomRecord(bloom_id="b2", specimen_id="s1", opened_at=opened, ended_at=opened))


def test_confidence_calibration_separates_buckets() -> None:
    buckets = calibrate_confidence([
        CalibrationObservation(prediction_id="p1", confidence=0.1, correct=False),
        CalibrationObservation(prediction_id="p2", confidence=0.9, correct=True),
    ])
    assert len(buckets) == 2
    assert buckets[0].observed_accuracy == 0
    assert buckets[1].observed_accuracy == 1


def test_herbarium_interpretation_requires_a_proposed_field() -> None:
    with pytest.raises(ValueError):
        validate_herbarium_interpretation(HerbariumInterpretation(interpretation_id="h1", image_id="img", evidence_region_ids=["r1"], confidence=0.5))


def test_grant_package_requires_core_sections_and_disables_submission() -> None:
    sections = [GrantSection(section_id=item, title=item.title(), body="text", evidence_ids=["e1"]) for item in ["need", "objectives", "methods", "outcomes", "budget"]]
    package = assemble_grant_package("g1", "Funder", "opp", sections)
    assert package.submission_enabled is False
    with pytest.raises(ValueError):
        assemble_grant_package("g2", "Funder", "opp", sections[:-1])


def test_schema_compatibility_flags_removed_required_fields() -> None:
    previous = EventSchema(event_type="artifact.created", version=1, required_fields={"artifact_id", "checksum"})
    candidate = EventSchema(event_type="artifact.created", version=2, required_fields={"artifact_id"})
    result = assess_schema_compatibility(previous, candidate)
    assert result.compatible is False
    assert result.missing_required_fields == ["checksum"]


def test_critical_path_is_deterministic_and_rejects_cycles() -> None:
    builds = [
        CriticalPathBuild(build_id="a", duration_units=2),
        CriticalPathBuild(build_id="b", duration_units=5, dependency_ids=["a"]),
        CriticalPathBuild(build_id="c", duration_units=1, dependency_ids=["a"]),
    ]
    result = calculate_critical_path(builds)
    assert result.ordered_build_ids == ["a", "b"]
    assert result.total_duration_units == 7
    with pytest.raises(ValueError):
        calculate_critical_path([
            CriticalPathBuild(build_id="a", duration_units=1, dependency_ids=["b"]),
            CriticalPathBuild(build_id="b", duration_units=1, dependency_ids=["a"]),
        ])


def test_duplicate_architecture_detection_returns_candidates_only() -> None:
    result = detect_duplicate_architectures([
        ArchitectureFingerprint(architecture_id="a", title="Glossary", normalized_terms={"glossary", "figures", "education"}, dependency_ids={"brain"}),
        ArchitectureFingerprint(architecture_id="b", title="Explorer", normalized_terms={"glossary", "figures", "education"}, dependency_ids={"brain"}),
        ArchitectureFingerprint(architecture_id="c", title="Atlas", normalized_terms={"maps", "climate"}),
    ])
    assert [(item.left_id, item.right_id) for item in result] == [("a", "b")]
    assert result[0].status == "candidate"
