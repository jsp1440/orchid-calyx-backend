from __future__ import annotations

from pathlib import Path

import pytest

from runtime.environmental_intelligence import EnvironmentalIntelligenceService


def record(record_id: str, *, cell_id: str, observation_state: str = "observed", reviewed: bool = True) -> dict:
    return {
        "record_id": record_id,
        "canonical_taxon_id": "taxon:laelia-anceps",
        "accepted_name": "Laelia anceps",
        "occurrence_id": f"occ:{record_id}",
        "climate_variables": {"temperature_c": 18.0 + len(record_id), "precipitation_mm": 900 + len(record_id)},
        "elevation": {"meters": 1200 + len(record_id)},
        "substrate": ["epiphytic bark"],
        "habitat": ["seasonally dry forest"],
        "temporal_coverage": {"observed_at": "2024-01-01"},
        "spatial_resolution": {"cell_id": cell_id, "meters": 1000},
        "source": {"uri": f"doi:10.0000/{record_id}", "license": "CC-BY-4.0"},
        "observation_state": observation_state,
        "uncertainty": {"coordinate_uncertainty_m": 100},
        "provenance": {"source_record_id": record_id, "ingest": "fixture"},
        "review_state": "accepted_as_evidence" if reviewed else "candidate",
    }


def test_environmental_record_preserves_source_license_and_state(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    item = service.register_record("owner-a", record("r1", cell_id="cell-a"), actor="owner-a")
    assert item["source"]["license"] == "CC-BY-4.0"
    assert item["observation_state"] == "observed"
    assert item["unsupported_causal_claims_authorized"] is False
    assert item["production_graph_mutation_authorized"] is False


def test_environmental_record_replay_is_idempotent_and_conflicts_fail_closed(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    first = service.register_record("owner-a", record("r1", cell_id="cell-a"), actor="owner-a")
    replay = service.register_record("owner-a", record("r1", cell_id="cell-a"), actor="owner-a")
    assert replay["record_digest"] == first["record_digest"]
    assert replay["created_at"] == first["created_at"]
    conflicting = record("r1", cell_id="cell-a")
    conflicting["habitat"] = ["cloud forest"]
    with pytest.raises(ValueError, match="ENV_IMMUTABLE_RECORD_CONFLICT"):
        service.register_record("owner-a", conflicting, actor="owner-a")


def test_envelope_separates_observed_and_modeled_and_warns_sampling_bias(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    service.register_record("owner-a", record("r1", cell_id="same"), actor="owner-a")
    service.register_record("owner-a", record("r2", cell_id="same", observation_state="modeled"), actor="owner-a")
    envelope = service.assemble_envelope("owner-a", "taxon:laelia-anceps")
    assert envelope["observed_record_count"] == 1
    assert envelope["modeled_record_count"] == 1
    assert "LOW_SAMPLE_COUNT" in envelope["sampling_bias_warnings"]
    assert "SPATIAL_CLUSTERING_RISK" in envelope["sampling_bias_warnings"]
    assert envelope["causal_interpretation"] == "not_authorized"


def test_unreviewed_records_are_explicitly_flagged(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    service.register_record("owner-a", record("r1", cell_id="a", reviewed=False), actor="owner-a")
    envelope = service.assemble_envelope("owner-a", "taxon:laelia-anceps")
    assert envelope["review_basis"] == "candidate_records"
    assert "UNREVIEWED_RECORDS_USED" in envelope["sampling_bias_warnings"]


def test_rejected_records_never_contribute_to_envelope(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    service.register_record("owner-a", record("good", cell_id="a", reviewed=False), actor="owner-a")
    service.register_record("owner-a", record("bad", cell_id="b", reviewed=False), actor="owner-a")
    service.review_record("owner-a", "bad", state="rejected", reviewer="owner-a", rationale="bad evidence")
    envelope = service.assemble_envelope("owner-a", "taxon:laelia-anceps")
    assert envelope["record_count"] == 1
    assert envelope["rejected_record_count"] == 1
    assert envelope["source_uris"] == ["doi:10.0000/good"]


def test_accepted_name_conflict_is_explicit_not_arbitrarily_selected(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    service.register_record("owner-a", record("r1", cell_id="a"), actor="owner-a")
    second = record("r2", cell_id="b")
    second["accepted_name"] = "Laelia anceps subsp. dawsonii"
    service.register_record("owner-a", second, actor="owner-a")
    envelope = service.assemble_envelope("owner-a", "taxon:laelia-anceps")
    assert envelope["accepted_name"] is None
    assert len(envelope["accepted_names"]) == 2
    assert "ACCEPTED_NAME_CONFLICT" in envelope["sampling_bias_warnings"]


def test_atlas_handoff_is_provenance_bearing_and_nonpublishing(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    service.register_record("owner-a", record("r1", cell_id="a"), actor="owner-a")
    handoff = service.atlas_handoff("owner-a", "taxon:laelia-anceps")
    assert handoff["atlas_layer_family"] == "earth_systems.environmental_envelope"
    assert handoff["provenance_required"] is True
    assert handoff["uncertainty_preserved"] is True
    assert handoff["publication_status"] == "candidate"
    assert handoff["scientific_publication_authorized"] is False


def test_readiness_never_authorizes_import_publication_or_graph_write(tmp_path: Path):
    service = EnvironmentalIntelligenceService(tmp_path)
    service.register_record("owner-a", record("r1", cell_id="a", reviewed=False), actor="owner-a")
    readiness = service.readiness("owner-a")
    assert readiness["pending_review_ids"] == ["r1"]
    assert readiness["live_production_import_authorized"] is False
    assert readiness["scientific_publication_authorized"] is False
    assert readiness["production_graph_mutation_authorized"] is False
    assert readiness["deployment_authorized"] is False
