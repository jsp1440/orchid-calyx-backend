"""Exact-identifier taxonomy-to-image relationship population.

This module performs no database I/O. It converts canonical record-media links
into provenance-bearing relationship candidates and rejects ambiguous matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.relationship_integration import RelationshipLink


@dataclass(frozen=True)
class MediaAsset:
    media_id: str
    source: str
    source_record_id: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class RecordMediaLink:
    record_domain: str
    record_id: str
    media_id: str
    source_table: str = "oc_core.record_media_link"


@dataclass(frozen=True)
class PopulationResult:
    candidates: tuple[RelationshipLink, ...]
    rejected: tuple[dict[str, Any], ...]

    def summary(self) -> dict[str, Any]:
        return {
            "candidate_links": len(self.candidates),
            "linked_taxa": len({item.taxon_id for item in self.candidates}),
            "rejected": len(self.rejected),
            "rejection_reasons": sorted({item["reason"] for item in self.rejected}),
        }


def build_taxonomy_image_candidates(
    links: list[RecordMediaLink],
    assets: dict[str, MediaAsset],
    canonical_taxon_ids: set[str],
) -> PopulationResult:
    """Build verified candidates only from exact canonical identifiers."""
    candidates: list[RelationshipLink] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for link in links:
        if link.record_domain not in {"taxonomy", "taxon"}:
            rejected.append({"link": link, "reason": "unsupported_record_domain"})
            continue
        if link.record_id not in canonical_taxon_ids:
            rejected.append({"link": link, "reason": "unknown_taxon_id"})
            continue
        asset = assets.get(link.media_id)
        if asset is None:
            rejected.append({"link": link, "reason": "missing_media_asset"})
            continue
        edge_key = (link.record_id, link.media_id)
        if edge_key in seen:
            rejected.append({"link": link, "reason": "duplicate_record_media_link"})
            continue
        seen.add(edge_key)
        candidates.append(
            RelationshipLink(
                source_domain="taxonomy",
                source_record_id=link.record_id,
                target_domain="images",
                target_record_id=link.media_id,
                relationship_type="has_image",
                taxon_id=link.record_id,
                match_method="canonical_record_media_link",
                confidence=1.0,
                validation_status="verified",
                provenance={
                    "relationship_source": link.source_table,
                    "asset_source": "oc_core.media_assets",
                    "media_provider": asset.source,
                    "provider_record_id": asset.source_record_id,
                    "license": asset.license,
                },
            ).validated()
        )

    return PopulationResult(tuple(candidates), tuple(rejected))
