from pathlib import Path

import pytest

from app.trait_genomics.discovery import TraitGenomicsDiscoveryEngine
from app.trait_genomics.models import DiscoveryDataset, EvidenceKind, EvidenceRecord
from app.trait_genomics.zenodo import ZenodoArchiveBridge


def record(evidence_id: str, taxon: str, kind: EvidenceKind, predicate: str, **kwargs):
    return EvidenceRecord(
        evidence_id=evidence_id,
        taxon_id=taxon,
        kind=kind,
        predicate=predicate,
        source_id="doi:10.example/hardening",
        **kwargs,
    )


def complete_dataset(dataset_id: str = "safe-dataset") -> DiscoveryDataset:
    records = []
    for taxon in ("taxon:a", "taxon:b"):
        records.extend(
            [
                record(
                    f"{taxon}:trait",
                    taxon,
                    EvidenceKind.OBSERVED_TRAIT,
                    "spur_length",
                    value="long",
                ),
                record(
                    f"{taxon}:interaction",
                    taxon,
                    EvidenceKind.ECOLOGICAL_INTERACTION,
                    "pollinatedBy",
                    target_taxon_id="pollinator:x",
                ),
                record(
                    f"{taxon}:molecular",
                    taxon,
                    EvidenceKind.GENETIC_ASSOCIATION,
                    "associatedWithTrait",
                    gene_id="GENE1",
                ),
            ]
        )
    return DiscoveryDataset(dataset_id=dataset_id, title="Hardening test", records=records)


def test_release_path_cannot_escape_configured_staging_root(tmp_path: Path):
    dataset = complete_dataset("../escape")
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    with pytest.raises(ValueError, match="path separators"):
        ZenodoArchiveBridge().build_release(dataset, result, tmp_path)


def test_release_rejects_mismatched_result_identity(tmp_path: Path):
    dataset = complete_dataset()
    other = complete_dataset("other-dataset")
    result = TraitGenomicsDiscoveryEngine().discover(other)
    with pytest.raises(ValueError, match="dataset_id"):
        ZenodoArchiveBridge().build_release(dataset, result, tmp_path)


def test_release_stays_beneath_staging_root(tmp_path: Path):
    dataset = complete_dataset()
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    release = ZenodoArchiveBridge().build_release(dataset, result, tmp_path)
    assert release.parent == tmp_path.resolve()
    assert release.name == dataset.dataset_id
    assert (release / "manifest.json").exists()
