from __future__ import annotations

from pathlib import Path

from app.trait_genomics.models import DiscoveryDataset, EvidenceKind, EvidenceRecord
from app.trait_genomics.release_service import ScientificArchiveReleaseService
from app.trait_genomics.zenodo import ZenodoArchiveBridge, ZenodoConfig


class FakeRepository:
    def __init__(self, existing=None):
        self.existing = existing
        self.saved = []

    def find_archive_release_by_fingerprint(self, release_fingerprint: str, *, provider: str = "zenodo"):
        return self.existing

    def save_archive_release(self, **kwargs):
        self.saved.append(kwargs)
        return {
            "release_id": f"zenodo:{kwargs['deposition_id']}",
            **kwargs,
        }


class FakeBridge(ZenodoArchiveBridge):
    def __init__(self, *, fail_upload: bool = False):
        super().__init__(ZenodoConfig(token="test", base_url="https://zenodo.example/api", community="orchid-continuum"))
        self.created = 0
        self.uploaded = 0
        self.fail_upload = fail_upload

    def create_draft(self, *, title, description, creators):
        self.created += 1
        return {
            "id": 12345,
            "state": "unsubmitted",
            "submitted": False,
            "doi": None,
            "links": {
                "html": "https://zenodo.example/deposit/12345",
                "bucket": "https://zenodo.example/api/files/bucket-12345",
            },
        }

    def upload_release_files(self, draft, release_dir):
        self.uploaded += 1
        if self.fail_upload:
            raise RuntimeError("synthetic upload failure")
        return sorted(path.name for path in Path(release_dir).iterdir() if path.is_file())


def dataset() -> DiscoveryDataset:
    records = []
    for taxon in ("taxon:a", "taxon:b"):
        records.extend(
            [
                EvidenceRecord(
                    evidence_id=f"{taxon}:trait",
                    taxon_id=taxon,
                    kind=EvidenceKind.OBSERVED_TRAIT,
                    predicate="spur_length",
                    value="long",
                    source_id="doi:test",
                ),
                EvidenceRecord(
                    evidence_id=f"{taxon}:interaction",
                    taxon_id=taxon,
                    kind=EvidenceKind.ECOLOGICAL_INTERACTION,
                    predicate="pollinatedBy",
                    target_taxon_id="pollinator:x",
                    source_id="doi:test",
                ),
                EvidenceRecord(
                    evidence_id=f"{taxon}:gene",
                    taxon_id=taxon,
                    kind=EvidenceKind.GENETIC_ASSOCIATION,
                    predicate="associatedWithTrait",
                    gene_id="GENE1",
                    source_id="doi:test",
                ),
            ]
        )
    return DiscoveryDataset(dataset_id="tig-release", title="TIG release", records=records)


def test_release_service_builds_uploads_and_ledgers_draft(tmp_path):
    repository = FakeRepository()
    bridge = FakeBridge()
    service = ScientificArchiveReleaseService(
        bridge=bridge,
        repository=repository,  # type: ignore[arg-type]
        staging_root=tmp_path,
    )

    result = service.create_zenodo_draft(dataset(), creators=[{"name": "Parham, Jeff"}])

    assert result["deposition_id"] == 12345
    assert result["state"] == "draft_uploaded"
    assert result["idempotent_reuse"] is False
    assert bridge.created == 1
    assert bridge.uploaded == 1
    assert len(repository.saved) == 2
    assert repository.saved[0]["state"] == "draft_created"
    assert repository.saved[1]["state"] == "draft_uploaded"
    assert "manifest.json" in result["uploaded_files"]


def test_release_service_reuses_existing_fingerprint_without_new_deposit(tmp_path):
    probe_repository = FakeRepository()
    probe_bridge = FakeBridge()
    probe_service = ScientificArchiveReleaseService(
        bridge=probe_bridge,
        repository=probe_repository,  # type: ignore[arg-type]
        staging_root=tmp_path / "probe",
    )
    first = probe_service.create_zenodo_draft(dataset(), creators=[{"name": "Parham, Jeff"}])

    existing = {
        "release_id": first["release_id"],
        "dataset_id": first["dataset_id"],
        "deposition_id": first["deposition_id"],
        "state": first["state"],
        "release_fingerprint": first["release_fingerprint"],
        "release_path": first["release_path"],
        "provider_payload": first["provider_payload"],
    }
    repository = FakeRepository(existing=existing)
    bridge = FakeBridge()
    service = ScientificArchiveReleaseService(
        bridge=bridge,
        repository=repository,  # type: ignore[arg-type]
        staging_root=tmp_path / "second",
    )

    reused = service.create_zenodo_draft(dataset(), creators=[{"name": "Parham, Jeff"}])

    assert reused["idempotent_reuse"] is True
    assert reused["deposition_id"] == 12345
    assert bridge.created == 0
    assert bridge.uploaded == 0
    assert repository.saved == []


def test_release_service_records_upload_failure(tmp_path):
    repository = FakeRepository()
    bridge = FakeBridge(fail_upload=True)
    service = ScientificArchiveReleaseService(
        bridge=bridge,
        repository=repository,  # type: ignore[arg-type]
        staging_root=tmp_path,
    )

    try:
        service.create_zenodo_draft(dataset(), creators=[{"name": "Parham, Jeff"}])
    except RuntimeError as exc:
        assert "synthetic upload failure" in str(exc)
    else:
        raise AssertionError("Release service unexpectedly ignored upload failure")

    assert [item["state"] for item in repository.saved] == ["draft_created", "upload_failed"]
    assert "synthetic upload failure" in repository.saved[-1]["provider_payload"]["error"]
