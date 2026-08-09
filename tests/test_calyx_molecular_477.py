from __future__ import annotations

from pathlib import Path

import pytest

from runtime.molecular_evidence import MolecularEvidenceService


def resolved_payload() -> dict:
    return {
        "evidence_id": "ev-1",
        "accession": "ORCHID-ITS-001",
        "marker": "ITS",
        "source_database": "fixture-db",
        "voucher": {"institution_code": "OC", "catalog_number": "V-1"},
        "specimen_provenance": {"collector": "Fixture Botanist", "country": "fixture"},
        "submitted_name": "Laelia anceps",
        "canonical_taxon_id": "taxon:laelia-anceps",
        "accepted_name": "Laelia anceps",
        "evidence_span": {"source_uri": "doi:10.0000/fixture", "start": 10, "end": 52},
        "confidence": 0.82,
        "conflicts": [],
    }


def test_resolved_sequence_record_preserves_provenance_and_never_claims_truth(tmp_path: Path):
    service = MolecularEvidenceService(tmp_path)
    record = service.register_sequence_evidence("owner-a", resolved_payload(), actor="owner-a")
    assert record["accession"] == "ORCHID-ITS-001"
    assert record["taxon_resolution_state"] == "resolved"
    assert record["evidence_span"]["source_uri"] == "doi:10.0000/fixture"
    assert record["live_sequence_harvesting_authorized"] is False
    assert record["phylogenetic_truth_claim_authorized"] is False
    assert record["scientific_publication_authorized"] is False
    assert record["production_graph_mutation_authorized"] is False


def test_unresolved_taxon_enters_ambiguity_queue_and_cannot_be_accepted(tmp_path: Path):
    service = MolecularEvidenceService(tmp_path)
    payload = resolved_payload() | {
        "evidence_id": "ev-ambiguous",
        "canonical_taxon_id": None,
        "accepted_name": None,
        "conflicts": ["submitted name maps to multiple candidates"],
    }
    record = service.register_sequence_evidence("owner-a", payload, actor="owner-a")
    assert record["review_state"] == "needs_review"
    queue = service.ambiguity_queue("owner-a")
    assert [item["evidence_id"] for item in queue["items"]] == ["ev-ambiguous"]
    with pytest.raises(ValueError, match="MOLECULAR_TAXON_RESOLUTION_REQUIRED"):
        service.review_evidence(
            "owner-a", "ev-ambiguous", state="accepted_as_evidence",
            reviewer="human-reviewer", rationale="cannot accept until identity is resolved",
        )


def test_analysis_artifact_is_evidence_bound_and_nonpublishing(tmp_path: Path):
    service = MolecularEvidenceService(tmp_path)
    service.register_sequence_evidence("owner-a", resolved_payload(), actor="owner-a")
    artifact = service.register_analysis_artifact(
        "owner-a", "ev-1",
        {
            "artifact_id": "alignment-1", "analysis_type": "alignment",
            "content": '{"fixture":"alignment"}', "media_type": "application/json",
        },
    )
    assert artifact["artifact_id"] == "molecular-analysis:alignment-1"
    assert artifact["publication_authorized"] is False
    evidence = service.get_evidence("owner-a", "ev-1")
    assert artifact["artifact_id"] in evidence["alignment_or_analysis_artifact_ids"]


def test_claim_rejects_analysis_artifact_not_bound_to_source_evidence(tmp_path: Path):
    service = MolecularEvidenceService(tmp_path)
    service.register_sequence_evidence("owner-a", resolved_payload(), actor="owner-a")
    with pytest.raises(ValueError, match="PHYLOGENETIC_ANALYSIS_ARTIFACT_NOT_BOUND"):
        service.record_phylogenetic_claim(
            "owner-a", "ev-1",
            {
                "claim_id": "claim-unbound", "claim_type": "sister_relationship",
                "statement": "Fixture claim.", "analysis_artifact_ids": ["molecular-analysis:other"],
            },
            actor="owner-a",
        )


def test_phylogenetic_claim_requires_reviewed_source_evidence_and_never_becomes_truth(tmp_path: Path):
    service = MolecularEvidenceService(tmp_path)
    service.register_sequence_evidence("owner-a", resolved_payload(), actor="owner-a")
    claim = service.record_phylogenetic_claim(
        "owner-a", "ev-1",
        {
            "claim_id": "claim-1", "claim_type": "sister_relationship",
            "statement": "Fixture analysis places taxon A near taxon B.",
            "confidence": 0.7, "analysis_artifact_ids": [],
        },
        actor="owner-a",
    )
    assert claim["review_state"] == "needs_review"
    assert claim["truth_status"] == "not_asserted"
    with pytest.raises(ValueError, match="PHYLOGENETIC_SOURCE_EVIDENCE_NOT_ACCEPTED"):
        service.review_claim(
            "owner-a", "claim-1", state="accepted_as_evidence",
            reviewer="human-reviewer", rationale="must first review source evidence",
        )
    service.review_evidence(
        "owner-a", "ev-1", state="accepted_as_evidence",
        reviewer="human-reviewer", rationale="voucher, identity, and evidence span reviewed",
    )
    reviewed = service.review_claim(
        "owner-a", "claim-1", state="accepted_as_evidence",
        reviewer="human-reviewer", rationale="usable reviewed evidence, not canonical phylogenetic truth",
    )
    assert reviewed["truth_status"] == "reviewed_evidence_only"
    assert reviewed["scientific_publication_authorized"] is False


def test_owner_isolation_and_readiness(tmp_path: Path):
    service = MolecularEvidenceService(tmp_path)
    service.register_sequence_evidence("owner-a", resolved_payload(), actor="owner-a")
    with pytest.raises(FileNotFoundError):
        service.get_evidence("owner-b", "ev-1")
    readiness = service.readiness("owner-a")
    assert readiness["evidence_count"] == 1
    assert readiness["deployment_authorized"] is False
    assert readiness["production_graph_mutation_authorized"] is False
