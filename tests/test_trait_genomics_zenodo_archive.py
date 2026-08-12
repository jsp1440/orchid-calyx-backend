import json

from app.trait_genomics.discovery import TraitGenomicsDiscoveryEngine
from app.trait_genomics.models import DiscoveryDataset, EvidenceKind, EvidenceRecord
from app.trait_genomics.zenodo import ZenodoArchiveBridge, ZenodoConfig


def test_release_contains_checksummed_evidence_and_hypotheses(tmp_path):
    dataset = DiscoveryDataset(
        dataset_id="release-001",
        title="Orchid trait interaction genomics",
        records=[
            EvidenceRecord(
                evidence_id="e1",
                taxon_id="taxon:1",
                kind=EvidenceKind.OBSERVED_TRAIT,
                predicate="flower_color",
                value="red",
                source_id="doi:test",
            )
        ],
        source_snapshot_ids=["traitbank:2026-08"],
    )
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    bridge = ZenodoArchiveBridge(ZenodoConfig(token=None))
    release = bridge.build_release(dataset, result, tmp_path)
    manifest = json.loads((release / "manifest.json").read_text())
    assert manifest["dataset_id"] == "release-001"
    assert manifest["evidence_count"] == 1
    assert "trait_interaction_genomics_evidence.jsonl" in manifest["checksums_sha256"]
    assert (release / "README.md").is_file()


def test_zenodo_write_requires_token():
    bridge = ZenodoArchiveBridge(ZenodoConfig(token=None))
    try:
        bridge.create_draft(title="x", description="y", creators=[{"name": "Parham, Jeffery"}])
    except RuntimeError as exc:
        assert "ZENODO_ACCESS_TOKEN" in str(exc)
    else:
        raise AssertionError("Zenodo write unexpectedly succeeded without a token")
