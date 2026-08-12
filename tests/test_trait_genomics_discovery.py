from app.trait_genomics.discovery import TraitGenomicsDiscoveryEngine
from app.trait_genomics.models import DiscoveryDataset, EvidenceKind, EvidenceRecord


def record(evidence_id: str, taxon: str, kind: EvidenceKind, predicate: str, **kwargs):
    return EvidenceRecord(
        evidence_id=evidence_id,
        taxon_id=taxon,
        kind=kind,
        predicate=predicate,
        source_id="doi:10.example/test",
        **kwargs,
    )


def test_repeated_trait_interaction_molecular_pattern_becomes_noncausal_candidate():
    records = []
    for taxon in ("taxon:a", "taxon:b"):
        records.extend(
            [
                record(f"{taxon}:trait", taxon, EvidenceKind.OBSERVED_TRAIT, "spur_length", value="long", confidence=0.9, direct_observation=True),
                record(f"{taxon}:poll", taxon, EvidenceKind.ECOLOGICAL_INTERACTION, "pollinatedBy", target_taxon_id="pollinator:long_tongued", confidence=0.9),
                record(f"{taxon}:gene", taxon, EvidenceKind.GENETIC_ASSOCIATION, "associatedWithTrait", gene_id="GENE1", confidence=0.8),
            ]
        )
    dataset = DiscoveryDataset(dataset_id="tig-test", title="test", records=records)
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    assert len(result.hypotheses) == 1
    hypothesis = result.hypotheses[0]
    assert hypothesis.independent_taxa_count == 2
    assert hypothesis.molecular_feature == "GENE1"
    assert hypothesis.interaction_predicate == "pollinatedBy"
    assert hypothesis.causal_claim is False
    assert hypothesis.status == "candidate"


def test_single_taxon_pattern_is_not_promoted_to_discovery_candidate():
    dataset = DiscoveryDataset(
        dataset_id="single",
        title="single",
        records=[
            record("t", "taxon:a", EvidenceKind.OBSERVED_TRAIT, "color", value="red"),
            record("i", "taxon:a", EvidenceKind.ECOLOGICAL_INTERACTION, "pollinatedBy", target_taxon_id="bird:x"),
        ],
    )
    assert TraitGenomicsDiscoveryEngine().discover(dataset).hypotheses == []
