from __future__ import annotations

import hashlib
import json

from runtime.propagation_research_dataset import (
    DATASET_SCHEMA_VERSION,
    canonical_rows_sha256,
    dataset_package,
    dataset_readiness,
    propagation_dataset_rows,
    queen_of_sheba_preview_evidence,
    research_station_registration_packet,
)


def _calyx_617_reference_checksum(rows):
    stable = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def test_flat_rows_preserve_six_reported_observations_without_inference():
    rows = propagation_dataset_rows()
    assert len(rows) == 6
    assert {row["authority"] for row in rows} == {"reported"}
    assert all(row["reproducible_from_current_evidence"] is False for row in rows)
    assert any(row["quantitative_value"] is None for row in rows)


def test_dataset_checksum_matches_calyx_617_canonical_row_contract():
    rows = propagation_dataset_rows()
    assert canonical_rows_sha256(rows) == _calyx_617_reference_checksum(rows)


def test_preview_evidence_remains_bounded_below_full_text_authority():
    evidence = queen_of_sheba_preview_evidence()
    assert len(evidence) == 6
    assert all(item.evidence_level == "publisher_preview_figure_caption" for item in evidence)
    assert all(item.full_text_verified is False for item in evidence)
    assert all(item.publication_authority is False for item in evidence)
    charcoal = next(item for item in evidence if item.evidence_id == "tv-preview-002")
    assert charcoal.treatment_value == "0.1"
    assert charcoal.treatment_unit == "% w/v"


def test_package_has_deterministic_rows_and_separate_supplemental_evidence():
    first = dataset_package()
    second = dataset_package()
    assert first == second
    assert first["schema_version"] == DATASET_SCHEMA_VERSION
    assert first["row_count"] == 6
    assert len(first["supplemental_evidence"]) == 6
    assert first["source_completeness"] == "abstract_verified"
    assert first["full_text_required"] is True
    assert first["scientific_publication_authorized"] is False
    assert first["knowledge_graph_mutation_authorized"] is False


def test_registration_packet_matches_research_station_dataset_contract():
    packet = research_station_registration_packet()
    assert packet["dataset_id"] == "dataset-thelymitra-variegata-propagation-v1"
    assert len(packet["checksum_sha256"]) == 64
    assert packet["schema_ref"] == "calyx://schemas/propagation-evidence-dataset/v1"
    assert packet["provenance"]["calyx_build"] == "CALYX-639"
    assert packet["provenance"]["candidate_only"] is True
    assert packet["provenance"]["full_text_required"] is True


def test_readiness_does_not_claim_rows_have_been_persisted():
    readiness = dataset_readiness()
    assert readiness["registration_packet_ready"] is True
    assert readiness["rows_ready_for_calyx_617_analysis"] is True
    assert readiness["rows_persisted_in_research_station"] is False
    assert "CALYX-631" in readiness["row_persistence_dependency"]
    assert readiness["automatic_registration_performed"] is False
    assert readiness["scientific_publication_authorized"] is False
