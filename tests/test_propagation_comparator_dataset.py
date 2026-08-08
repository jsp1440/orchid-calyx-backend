import hashlib
import json

from runtime.propagation_comparator_dataset import (
    comparator_dataset_package,
    comparator_dataset_readiness,
    comparator_dataset_rows,
    comparator_registration_packet,
    canonical_rows_sha256,
)


def _calyx_617_reference_checksum(rows):
    stable = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def test_comparator_dataset_preserves_nine_rows_and_four_taxa():
    rows = comparator_dataset_rows()
    assert len(rows) == 9
    assert {row["taxon"] for row in rows} == {
        "Anoectochilus roxburghii",
        "Hemipilia cucullata",
        "Ipsea malabarica",
        "Spathoglottis plicata",
    }
    assert all(row["directly_about_thelymitra"] is False for row in rows)
    assert all(row["prediction_authority"] is False for row in rows)


def test_comparator_checksum_matches_calyx_617_contract():
    rows = comparator_dataset_rows()
    assert canonical_rows_sha256(rows) == _calyx_617_reference_checksum(rows)


def test_negative_and_meristem_evidence_survive_flattening():
    rows = comparator_dataset_rows()
    negative = next(row for row in rows if row["observation_id"] == "im-kin-negative-002")
    meristem = next(row for row in rows if row["observation_id"] == "ar-meristem-plb-001")
    assert negative["direction"] == "negative_for_plb_induction"
    assert meristem["explant"] == "axillary bud meristem"
    assert "without intervening callus" in meristem["response"]


def test_package_and_registration_are_deterministic_and_nonpredictive():
    first = comparator_dataset_package()
    second = comparator_dataset_package()
    assert first == second
    assert first["row_count"] == 9
    assert first["direct_thelymitra_evidence"] is False
    assert first["prediction_of_thelymitra_success"] is False
    packet = comparator_registration_packet()
    assert packet["dataset_id"] == "dataset-terrestrial-orchid-vegetative-plb-comparators-v1"
    assert len(packet["checksum_sha256"]) == 64
    assert packet["provenance"]["calyx_build"] == "CALYX-639B"


def test_readiness_refuses_to_claim_row_persistence_or_publication():
    readiness = comparator_dataset_readiness()
    assert readiness["registration_packet_ready"] is True
    assert readiness["rows_ready_for_calyx_617_analysis"] is True
    assert readiness["rows_persisted_in_research_station"] is False
    assert "CALYX-631" in readiness["row_persistence_dependency"]
    assert readiness["automatic_registration_performed"] is False
    assert readiness["scientific_publication_authorized"] is False
