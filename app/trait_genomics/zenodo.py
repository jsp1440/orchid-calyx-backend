from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DiscoveryDataset, DiscoveryResult


@dataclass(frozen=True)
class ZenodoConfig:
    token: str | None
    base_url: str = "https://zenodo.org/api"
    community: str | None = None

    @classmethod
    def from_env(cls) -> ZenodoConfig:
        base = os.getenv("ZENODO_API_BASE", "https://zenodo.org/api").rstrip("/")
        return cls(
            token=os.getenv("ZENODO_ACCESS_TOKEN"),
            base_url=base,
            community=os.getenv("ZENODO_COMMUNITY") or None,
        )


class ZenodoArchiveBridge:
    """Build reproducible TIG release packages and deposit them to Zenodo drafts."""

    def __init__(self, config: ZenodoConfig | None = None) -> None:
        self.config = config or ZenodoConfig.from_env()

    @staticmethod
    def _release_dir(root: str | Path, dataset_id: str) -> Path:
        root_path = Path(root).expanduser().resolve()
        if not dataset_id or dataset_id in {".", ".."}:
            raise ValueError("dataset_id must be a non-empty archive identifier")
        if Path(dataset_id).is_absolute() or "/" in dataset_id or "\\" in dataset_id:
            raise ValueError("dataset_id must not contain path separators")
        release_dir = (root_path / dataset_id).resolve()
        if release_dir.parent != root_path:
            raise ValueError("archive release path escapes configured staging root")
        return release_dir

    @staticmethod
    def _release_fingerprint(dataset_id: str, checksums: dict[str, str]) -> str:
        payload = json.dumps(
            {"dataset_id": dataset_id, "checksums_sha256": checksums},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def build_release(
        self,
        dataset: DiscoveryDataset,
        result: DiscoveryResult,
        root: str | Path,
    ) -> Path:
        if result.dataset_id != dataset.dataset_id:
            raise ValueError("DiscoveryResult dataset_id does not match DiscoveryDataset")
        if result.evidence_count != len(dataset.records):
            raise ValueError("DiscoveryResult evidence_count does not match dataset records")

        release_dir = self._release_dir(root, dataset.dataset_id)
        release_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = release_dir / "trait_interaction_genomics_evidence.jsonl"
        hypotheses_path = release_dir / "discovery_hypotheses.jsonl"
        manifest_path = release_dir / "manifest.json"
        readme_path = release_dir / "README.md"

        with evidence_path.open("w", encoding="utf-8") as handle:
            for record in dataset.records:
                handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")
        with hypotheses_path.open("w", encoding="utf-8") as handle:
            for hypothesis in result.hypotheses:
                handle.write(json.dumps(hypothesis.model_dump(mode="json"), sort_keys=True) + "\n")

        readme_path.write_text(
            "# Orchid Continuum Trait–Interaction–Genomics dataset\n\n"
            "This release contains provenance-bearing evidence and non-causal discovery hypotheses.\n"
            "The operational database remains authoritative for mutable review state; this package is a versioned scientific snapshot.\n"
            "Public publication requires explicit human review outside the automated draft pipeline.\n",
            encoding="utf-8",
        )

        checksums = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (evidence_path, hypotheses_path, readme_path)
        }
        release_fingerprint = self._release_fingerprint(dataset.dataset_id, checksums)
        manifest = {
            "schema_version": 1,
            "dataset_id": dataset.dataset_id,
            "title": dataset.title,
            "generated_at": result.generated_at.isoformat(),
            "source_snapshot_ids": dataset.source_snapshot_ids,
            "evidence_count": result.evidence_count,
            "trait_count": result.trait_count,
            "interaction_count": result.interaction_count,
            "molecular_count": result.molecular_count,
            "hypothesis_count": len(result.hypotheses),
            "checksums_sha256": checksums,
            "release_fingerprint": release_fingerprint,
            "archive_policy": "versioned_public_scientific_archive",
            "publication_policy": "draft_only_until_human_review",
            "causal_policy": "candidate hypotheses are non-causal until reviewed",
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return release_dir

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        if not self.config.token:
            raise RuntimeError("ZENODO_ACCESS_TOKEN is required for Zenodo deposit operations")
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Zenodo API error {exc.code}: {detail[:1000]}") from exc

    def create_draft(
        self,
        *,
        title: str,
        description: str,
        creators: list[dict[str, str]],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "title": title,
            "upload_type": "dataset",
            "description": description,
            "creators": creators,
        }
        if self.config.community:
            metadata["communities"] = [{"identifier": self.config.community}]
        payload = json.dumps({"metadata": metadata}).encode("utf-8")
        return self._request("POST", f"{self.config.base_url}/deposit/depositions", body=payload)

    def upload_release_files(
        self,
        draft: dict[str, Any],
        release_dir: str | Path,
    ) -> list[str]:
        bucket_url = str(draft.get("links", {}).get("bucket") or "").rstrip("/")
        if not bucket_url:
            raise RuntimeError("Zenodo draft response does not contain a file bucket URL")
        release_path = Path(release_dir).resolve()
        uploaded: list[str] = []
        for path in sorted(release_path.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            filename = urllib.parse.quote(path.name, safe="")
            self._request(
                "PUT",
                f"{bucket_url}/{filename}",
                body=path.read_bytes(),
                content_type="application/octet-stream",
            )
            uploaded.append(path.name)
        return uploaded

    @staticmethod
    def compact_draft_payload(draft: dict[str, Any], *, files: list[str] | None = None) -> dict[str, Any]:
        links = draft.get("links") or {}
        payload: dict[str, Any] = {
            "id": draft.get("id"),
            "state": draft.get("state"),
            "submitted": draft.get("submitted"),
            "doi": draft.get("doi"),
            "html": links.get("html"),
        }
        if files is not None:
            payload["files"] = files
        return payload

    def publish(self, deposition_id: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.config.base_url}/deposit/depositions/{deposition_id}/actions/publish",
            body=b"",
        )
