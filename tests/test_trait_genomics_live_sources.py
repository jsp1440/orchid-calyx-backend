from app.trait_genomics.discovery import TraitGenomicsDiscoveryEngine
from app.trait_genomics.live_sources import (
    make_live_dataset,
    map_interaction_row,
    map_molecular_association_row,
    map_phylogenetic_row,
    map_trait_row,
)
from app.trait_genomics.models import DiscoveryDataset, EvidenceKind, EvidenceRecord


def test_trait_mapping_requires_canonical_taxon_and_uses_conservative_confidence():
    missing_taxon = map_trait_row(
        {"trait_name": "flower_color", "trait_value": "red"},
        "oc_views.trait_resolved_v4",
    )
    assert missing_taxon is None

    record = map_trait_row(
        {
            "taxon_id": "taxon-1",
            "scientific_name": "Example orchid",
            "trait_name": "flower_color",
            "trait_value": "red",
            "support_count": 4,
        },
        "oc_views.trait_resolved_v4",
    )
    assert record is not None
    assert record.kind == EvidenceKind.INFERRED_TRAIT
    assert record.confidence == 0.5
    assert record.metadata["confidence_basis"] == "conservative_default_missing_source_confidence"
    assert record.metadata["support_count"] == 4


def test_interaction_mapping_requires_partner_identity():
    assert (
        map_interaction_row(
            {
                "taxon_id": "orchid-1",
                "interaction_type": "pollinated_by",
            },
            "oc_interactions.orchid_interaction_edges",
        )
        is None
    )

    record = map_interaction_row(
        {
            "taxon_id": "orchid-1",
            "interaction_type": "pollinated_by",
            "partner_taxon_id": "bee-1",
            "confidence_score": 0.9,
        },
        "oc_interactions.orchid_interaction_edges",
    )
    assert record is not None
    assert record.kind == EvidenceKind.ECOLOGICAL_INTERACTION
    assert record.target_taxon_id == "bee-1"
    assert record.confidence == 0.9


def test_raw_phylogenetic_sequence_is_context_not_genetic_association():
    phylo = map_phylogenetic_row(
        {
            "taxon_id": "orchid-1",
            "marker_name": "ITS",
            "accession": "AB123456",
        },
        "oc_phylogeny.taxon_sequences",
    )
    assert phylo is not None
    assert phylo.kind == EvidenceKind.PHYLOGENETIC_EVIDENCE

    dataset = DiscoveryDataset(
        dataset_id="phylo-context-only",
        title="context",
        records=[
            EvidenceRecord(
                evidence_id="trait-1",
                taxon_id="orchid-1",
                kind=EvidenceKind.OBSERVED_TRAIT,
                predicate="flower_color",
                value="red",
                source_id="test",
            ),
            EvidenceRecord(
                evidence_id="interaction-1",
                taxon_id="orchid-1",
                kind=EvidenceKind.ECOLOGICAL_INTERACTION,
                predicate="pollinated_by",
                target_taxon_id="bee-1",
                source_id="test",
            ),
            phylo,
        ],
    )
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    assert result.molecular_count == 0
    assert result.hypotheses == []


def test_named_molecular_marker_aligns_across_taxa_without_accession_collision():
    records = []
    for suffix, accession in (("a", "SEQ-A"), ("b", "SEQ-B")):
        taxon = f"orchid-{suffix}"
        records.extend(
            [
                EvidenceRecord(
                    evidence_id=f"trait-{suffix}",
                    taxon_id=taxon,
                    kind=EvidenceKind.OBSERVED_TRAIT,
                    predicate="flower_color",
                    value="red",
                    source_id="test",
                    confidence=0.9,
                ),
                EvidenceRecord(
                    evidence_id=f"interaction-{suffix}",
                    taxon_id=taxon,
                    kind=EvidenceKind.ECOLOGICAL_INTERACTION,
                    predicate="pollinated_by",
                    target_taxon_id="bee-shared",
                    source_id="test",
                    confidence=0.9,
                ),
            ]
        )
        molecular = map_molecular_association_row(
            {
                "taxon_id": taxon,
                "association_type": "associated_with_trait",
                "marker_name": "shared-marker",
                "accession": accession,
                "confidence_score": 0.9,
            },
            "oc_genomics.trait_associations",
        )
        assert molecular is not None
        records.append(molecular)

    dataset = DiscoveryDataset(
        dataset_id="shared-marker",
        title="shared marker",
        records=records,
    )
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].molecular_feature == "shared-marker"
    assert result.hypotheses[0].independent_taxa_count == 2


def test_live_dataset_identity_is_deterministic_for_same_evidence():
    record = EvidenceRecord(
        evidence_id="stable-1",
        taxon_id="orchid-1",
        kind=EvidenceKind.OBSERVED_TRAIT,
        predicate="flower_color",
        value="red",
        source_id="test",
    )
    first = make_live_dataset([record], source_tables=["oc_views.trait_resolved_v4"])
    second = make_live_dataset([record], source_tables=["oc_views.trait_resolved_v4"])
    assert first.dataset_id == second.dataset_id
    assert first.source_snapshot_ids == second.source_snapshot_ids
