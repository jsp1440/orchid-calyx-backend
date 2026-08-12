from __future__ import annotations

import pytest

from app.trait_genomics.discovery import TraitGenomicsDiscoveryEngine
from app.trait_genomics.models import DiscoveryDataset, EvidenceKind, EvidenceRecord
from app.trait_genomics.molecular_evidence import (
    MOLECULAR_DDL,
    MolecularEvidenceCandidate,
)


def test_candidate_requires_real_molecular_feature():
    with pytest.raises(ValueError, match="molecular feature"):
        MolecularEvidenceCandidate(
            canonical_taxon_id="taxon-1",
            evidence_kind="genetic_association",
            trait_predicate="flower_color",
            association_type="associated_with",
            evidence_text="A reported association.",
            source_id="doi:10.example/test",
            confidence_score=0.7,
        )


def test_candidate_id_is_deterministic():
    payload = {
        "canonical_taxon_id": "taxon-1",
        "scientific_name": "Example orchid",
        "evidence_kind": "expression_association",
        "trait_predicate": "floral_scent",
        "association_type": "differential_expression_associated_with",
        "gene_id": "OC-GENE-1",
        "evidence_text": "Expression differs with floral scent phenotype.",
        "source_id": "pmid:123",
        "confidence_score": 0.8,
    }
    first = MolecularEvidenceCandidate(**payload)
    second = MolecularEvidenceCandidate(**payload)
    assert first.stable_id() == second.stable_id()
    assert first.stable_id().startswith("tig-mol:")


def test_live_views_only_expose_human_accepted_evidence():
    normalized = " ".join(MOLECULAR_DDL.split()).lower()
    assert "where review_state='accepted'" in normalized
    assert "molecular_evidence_candidates" in normalized


def _record(evidence_id: str, taxon_id: str, kind: EvidenceKind, **kwargs):
    return EvidenceRecord(
        evidence_id=evidence_id,
        taxon_id=taxon_id,
        kind=kind,
        predicate=kwargs.pop("predicate"),
        source_id="test",
        confidence=0.9,
        **kwargs,
    )


def test_selection_association_can_complete_three_domain_candidate():
    records = []
    for taxon in ("taxon-a", "taxon-b"):
        records.extend(
            [
                _record(
                    f"trait-{taxon}",
                    taxon,
                    EvidenceKind.OBSERVED_TRAIT,
                    predicate="flower_color",
                    value="red",
                ),
                _record(
                    f"interaction-{taxon}",
                    taxon,
                    EvidenceKind.ECOLOGICAL_INTERACTION,
                    predicate="pollinated_by",
                    target_taxon_id="pollinator-x",
                ),
                _record(
                    f"selection-{taxon}",
                    taxon,
                    EvidenceKind.SELECTION_ASSOCIATION,
                    predicate="selection_associated_with",
                    gene_id="GENE-X",
                ),
            ]
        )
    dataset = DiscoveryDataset(dataset_id="selection-test", title="selection test", records=records)
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    assert result.molecular_count == 2
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].molecular_feature == "GENE-X"
