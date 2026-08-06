from datetime import datetime, timedelta, timezone

import pytest

from app.canonical_brain.priority_batch_four import (
    CitationRecord,
    DesignManualSection,
    EventReplayLedger,
    ExperimentRun,
    ImageAnnotation,
    IntegrationContract,
    InventoryRow,
    KeyCharacter,
    TemporalLayerSnapshot,
    WorkHealthRecord,
    assess_integration_readiness,
    build_annotation_set,
    build_citation_manifest,
    detect_temporal_change,
    generate_design_manual,
    generate_identification_key,
    stage_inventory_import,
    summarize_work_health,
)


def test_temporal_change_requires_order_and_shared_layer() -> None:
    early = TemporalLayerSnapshot(snapshot_id="s1", layer_id="forest", observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc), metric_value=100, evidence_ids=["e1"])
    late = TemporalLayerSnapshot(snapshot_id="s2", layer_id="forest", observed_at=datetime(2025, 1, 1, tzinfo=timezone.utc), metric_value=80, evidence_ids=["e2"])
    result = detect_temporal_change(early, late)
    assert result.absolute_change == -20
    assert result.percent_change == -20
    assert result.evidence_ids == ["e1", "e2"]
    with pytest.raises(ValueError):
        detect_temporal_change(late, early)


def test_experiment_completion_requires_outputs_and_forward_time() -> None:
    run = ExperimentRun(run_id="run:1", protocol_id="protocol:1", protocol_checksum="a" * 64, input_artifact_ids=["input:1"], started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    completed = run.complete(datetime(2026, 1, 2, tzinfo=timezone.utc), ["output:2", "output:1"])
    assert completed.status == "completed"
    assert completed.output_artifact_ids == ["output:1", "output:2"]
    with pytest.raises(ValueError):
        run.complete(run.started_at, ["output:1"])


def test_inventory_import_is_staged_and_rejects_duplicate_accessions() -> None:
    result = stage_inventory_import([
        InventoryRow(row_number=2, accession_number="A-1", taxon_name="Cattleya mossiae", location="GH-1", source="sheet"),
        InventoryRow(row_number=1, accession_number="A-1", taxon_name="Cattleya mossiae", location="GH-1", source="sheet"),
        InventoryRow(row_number=3, accession_number="A-2", taxon_name="", location="GH-2", source="sheet"),
    ])
    assert [item.row_number for item in result.accepted] == [1]
    assert result.rejected_rows == [2, 3]
    assert result.committed is False


def test_identification_key_is_deterministic() -> None:
    steps = generate_identification_key([
        KeyCharacter(character_id="leaf", question="Leaf form?", state_to_taxa={"pleated": ["t2", "t1"], "flat": ["t3"]}),
        KeyCharacter(character_id="habit", question="Growth habit?", state_to_taxa={"epiphytic": ["t1"], "terrestrial": ["t2"]}),
    ])
    assert [step.character_id for step in steps] == ["leaf", "habit"]
    assert steps[0].branches["pleated"] == ["t1", "t2"]


def test_annotation_set_rejects_cross_image_annotations_and_duplicates() -> None:
    annotation = ImageAnnotation(annotation_id="a1", image_id="img1", label="velamen", x=0.1, y=0.2, width=0.3, height=0.4, evidence_id="e1")
    first = build_annotation_set("set1", "img1", 1, [annotation])
    second = build_annotation_set("set1", "img1", 1, [annotation])
    assert first.checksum == second.checksum
    with pytest.raises(ValueError):
        build_annotation_set("set2", "img2", 1, [annotation])


def test_citation_manifest_is_sorted_and_rejects_duplicates() -> None:
    records = [
        CitationRecord(citation_id="c2", title="B", source_uri="https://example.org/b", license="CC-BY", accessed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        CitationRecord(citation_id="c1", title="A", source_uri="https://example.org/a", license="CC-BY", accessed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    manifest = build_citation_manifest(records)
    assert manifest.citation_ids == ["c1", "c2"]
    with pytest.raises(ValueError):
        build_citation_manifest([records[0], records[0]])


def test_event_replay_ledger_is_idempotent_and_conflict_safe() -> None:
    ledger = EventReplayLedger()
    assert ledger.accept("event:1", {"value": 1}) is True
    assert ledger.accept("event:1", {"value": 1}) is False
    with pytest.raises(ValueError):
        ledger.accept("event:1", {"value": 2})


def test_work_health_reports_stale_and_blocked_items() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    summary = summarize_work_health([
        WorkHealthRecord(work_id="w1", status="running", updated_at=now - timedelta(minutes=61), sla_minutes=60),
        WorkHealthRecord(work_id="w2", status="blocked", updated_at=now - timedelta(minutes=5), sla_minutes=60),
        WorkHealthRecord(work_id="w3", status="completed", updated_at=now - timedelta(days=2), sla_minutes=60),
    ], now)
    assert summary.stale_ids == ["w1"]
    assert summary.blocked_ids == ["w2"]
    assert summary.healthy_count == 2


def test_design_manual_is_deterministic_and_unpublished() -> None:
    generated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sections = [
        DesignManualSection(section_id="02", title="APIs", object_ids=["api:1"]),
        DesignManualSection(section_id="01", title="Vision", object_ids=["architecture:atlas"]),
    ]
    manual = generate_design_manual("architecture:atlas", sections, generated_at)
    assert [item.section_id for item in manual.sections] == ["01", "02"]
    assert manual.publication_enabled is False


def test_integration_readiness_requires_enabled_evidence_backed_contracts() -> None:
    report = assess_integration_readiness([
        IntegrationContract(contract_id="contract:1", producer="atlas", consumer="brain", event_type="map.created", schema_version="1", required_evidence_ids=["e1"], enabled=True),
        IntegrationContract(contract_id="contract:2", producer="vision", consumer="matrix", event_type="observation.created", schema_version="1", required_evidence_ids=["e2"], enabled=False),
    ])
    assert report.ready_contract_ids == ["contract:1"]
    assert report.blocked_contract_ids == ["contract:2"]
    assert report.all_ready is False
