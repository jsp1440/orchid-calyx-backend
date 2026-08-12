from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .discovery import TraitGenomicsDiscoveryEngine
from .models import DiscoveryDataset
from .repository import TraitGenomicsRepository
from .zenodo import ZenodoArchiveBridge


class ScientificArchiveReleaseService:
    """Build, deduplicate, deposit, upload, and ledger TIG scientific releases."""

    def __init__(
        self,
        *,
        bridge: ZenodoArchiveBridge | None = None,
        repository: TraitGenomicsRepository | None = None,
        staging_root: str | Path,
    ) -> None:
        self.bridge = bridge or ZenodoArchiveBridge()
        self.repository = repository or TraitGenomicsRepository()
        self.staging_root = Path(staging_root)

    def create_zenodo_draft(
        self,
        dataset: DiscoveryDataset,
        *,
        creators: list[dict[str, str]],
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        result = TraitGenomicsDiscoveryEngine().discover(dataset)
        release_dir = self.bridge.build_release(dataset, result, self.staging_root)
        manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
        release_fingerprint = manifest["release_fingerprint"]

        existing = self.repository.find_archive_release_by_fingerprint(release_fingerprint)
        if existing is not None:
            return {
                "release_id": existing["release_id"],
                "dataset_id": existing["dataset_id"],
                "deposition_id": existing["deposition_id"],
                "state": existing["state"],
                "release_fingerprint": existing["release_fingerprint"],
                "release_path": existing["release_path"],
                "provider_payload": existing["provider_payload"],
                "idempotent_reuse": True,
            }

        resolved_title = title or f"Orchid Continuum TIG dataset — {dataset.title}"
        resolved_description = description or (
            "Versioned Orchid Continuum Trait–Interaction–Genomics scientific snapshot. "
            "The archive contains provenance-bearing evidence and non-causal candidate "
            "hypotheses. Publication remains subject to explicit human scientific review."
        )

        draft = self.bridge.create_draft(
            title=resolved_title,
            description=resolved_description,
            creators=creators,
        )
        deposition_id = draft.get("id")
        if not isinstance(deposition_id, int):
            raise RuntimeError("Zenodo draft response did not contain an integer deposition id")

        compact = self.bridge.compact_draft_payload(draft)
        self.repository.save_archive_release(
            dataset_id=dataset.dataset_id,
            deposition_id=deposition_id,
            release_fingerprint=release_fingerprint,
            state="draft_created",
            community=self.bridge.config.community,
            manifest=manifest,
            provider_payload=compact,
            release_path=str(release_dir),
        )

        try:
            uploaded_files = self.bridge.upload_release_files(draft, release_dir)
        except Exception as exc:
            failed_payload = dict(compact)
            failed_payload["error"] = str(exc)[:1000]
            self.repository.save_archive_release(
                dataset_id=dataset.dataset_id,
                deposition_id=deposition_id,
                release_fingerprint=release_fingerprint,
                state="upload_failed",
                community=self.bridge.config.community,
                manifest=manifest,
                provider_payload=failed_payload,
                release_path=str(release_dir),
            )
            raise

        compact = self.bridge.compact_draft_payload(draft, files=uploaded_files)
        release = self.repository.save_archive_release(
            dataset_id=dataset.dataset_id,
            deposition_id=deposition_id,
            release_fingerprint=release_fingerprint,
            state="draft_uploaded",
            community=self.bridge.config.community,
            manifest=manifest,
            provider_payload=compact,
            release_path=str(release_dir),
        )
        return {
            "release_id": release["release_id"],
            "dataset_id": dataset.dataset_id,
            "deposition_id": deposition_id,
            "state": "draft_uploaded",
            "release_fingerprint": release_fingerprint,
            "release_path": str(release_dir),
            "uploaded_files": uploaded_files,
            "provider_payload": compact,
            "idempotent_reuse": False,
        }
