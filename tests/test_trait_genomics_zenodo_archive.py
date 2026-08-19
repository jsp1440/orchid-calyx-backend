import json
from pathlib import Path

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
    assert manifest["schema_version"] == 1
    assert manifest["publication_policy"] == "draft_only_until_human_review"
    assert len(manifest["release_fingerprint"]) == 64
    assert "trait_interaction_genomics_evidence.jsonl" in manifest["checksums_sha256"]
    assert "discovery_hypotheses.jsonl" in manifest["checksums_sha256"]
    assert "README.md" in manifest["checksums_sha256"]
    assert (release / "README.md").is_file()


def test_same_scientific_content_has_same_release_fingerprint(tmp_path):
    dataset = DiscoveryDataset(
        dataset_id="stable-release",
        title="Stable release",
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
    )
    result = TraitGenomicsDiscoveryEngine().discover(dataset)
    bridge = ZenodoArchiveBridge(ZenodoConfig(token=None))
    first = bridge.build_release(dataset, result, tmp_path / "one")
    second = bridge.build_release(dataset, result, tmp_path / "two")
    first_manifest = json.loads((first / "manifest.json").read_text())
    second_manifest = json.loads((second / "manifest.json").read_text())
    assert first_manifest["release_fingerprint"] == second_manifest["release_fingerprint"]


def test_upload_release_files_uses_zenodo_bucket(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    (release / "manifest.json").write_text("{}", encoding="utf-8")
    (release / "README.md").write_text("readme", encoding="utf-8")

    bridge = ZenodoArchiveBridge(ZenodoConfig(token="test-token"))
    calls = []

    def fake_request(method, url, *, body=None, content_type="application/json"):
        calls.append((method, url, body, content_type))
        return {"ok": True}

    bridge._request = fake_request  # type: ignore[method-assign]
    draft = {"links": {"bucket": "https://zenodo.example/api/files/bucket-1"}}
    uploaded = bridge.upload_release_files(draft, release)

    assert uploaded == ["README.md", "manifest.json"]
    assert [call[0] for call in calls] == ["PUT", "PUT"]
    assert calls[0][1].endswith("/README.md")
    assert calls[1][1].endswith("/manifest.json")
    assert all(call[3] == "application/octet-stream" for call in calls)


def test_upload_release_files_requires_bucket(tmp_path: Path):
    bridge = ZenodoArchiveBridge(ZenodoConfig(token="test-token"))
    try:
        bridge.upload_release_files({"links": {}}, tmp_path)
    except RuntimeError as exc:
        assert "bucket" in str(exc).lower()
    else:
        raise AssertionError("Zenodo file upload unexpectedly succeeded without a bucket")


def test_zenodo_write_requires_token():
    bridge = ZenodoArchiveBridge(ZenodoConfig(token=None))
    try:
        bridge.create_draft(title="x", description="y", creators=[{"name": "Parham, Jeffery"}])
    except RuntimeError as exc:
        assert "ZENODO_ACCESS_TOKEN" in str(exc)
    else:
        raise AssertionError("Zenodo write unexpectedly succeeded without a token")
