"""GBIF occurrence harvester plugin."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ...base import BaseHarvester
from ...models import HarvestPage
from ...registry import registry
from .client import GBIFClient


@registry.register
class GBIFHarvester(BaseHarvester):
    """Harvest occurrence records from the GBIF occurrence search API."""

    source = "gbif"

    def __init__(self, *, persistence: Any, checkpoints: Any, metrics: Any) -> None:
        super().__init__(
            persistence=persistence,
            checkpoints=checkpoints,
            metrics=metrics,
        )
        self.client = GBIFClient()

    def fetch_page(self, checkpoint: Mapping[str, Any] | None = None) -> HarvestPage:
        state = dict(checkpoint or {})
        offset = int(state.get("offset", 0))
        limit = int(state.get("limit", 300))
        payload = self.client.occurrence_search(
            offset=offset,
            limit=limit,
            taxon_key=_string_or_none(state.get("taxon_key")),
            scientific_name=_string_or_none(state.get("scientific_name")),
            media_type=_string_or_none(state.get("media_type")),
        )
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("GBIF payload results must be a list")
        records = tuple(record for record in raw_results if isinstance(record, Mapping))
        end_of_records = bool(payload.get("endOfRecords", False))
        next_offset = offset + len(records)
        return HarvestPage(
            records=records,
            next_checkpoint={
                "offset": next_offset,
                "limit": limit,
                "taxon_key": state.get("taxon_key"),
                "scientific_name": state.get("scientific_name"),
                "media_type": state.get("media_type"),
            },
            end_of_stream=end_of_records or not records,
        )

    def normalize(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        key = record.get("key")
        scientific_name = record.get("scientificName") or record.get("species")
        if key is None:
            raise ValueError("GBIF record is missing key")
        if not scientific_name:
            raise ValueError("GBIF record is missing scientific name")

        normalized: dict[str, Any] = {
            "source": self.source,
            "source_record_id": str(key),
            "scientific_name": str(scientific_name),
            "accepted_name": _string_or_none(record.get("acceptedScientificName")),
            "taxon_key": _string_or_none(record.get("taxonKey")),
            "occurrence_id": _string_or_none(record.get("occurrenceID")),
            "basis_of_record": _string_or_none(record.get("basisOfRecord")),
            "latitude": _float_or_none(record.get("decimalLatitude")),
            "longitude": _float_or_none(record.get("decimalLongitude")),
            "country_code": _string_or_none(record.get("countryCode")),
            "locality": _string_or_none(record.get("locality")),
            "event_date": _datetime_or_none(record.get("eventDate")),
            "recorded_by": _string_or_none(record.get("recordedBy")),
            "license": _string_or_none(record.get("license")),
            "references": _string_or_none(record.get("references")),
            "images": tuple(self.extract_images(record)),
            "raw": dict(record),
        }
        return normalized

    def validate(self, record: Mapping[str, Any]) -> bool:
        return bool(
            record.get("source_record_id")
            and record.get("scientific_name")
            and record.get("source") == self.source
        )

    def extract_images(self, record: Mapping[str, Any]):
        media = record.get("media") or ()
        if not isinstance(media, list):
            return ()
        images: list[Mapping[str, Any]] = []
        for index, item in enumerate(media):
            if not isinstance(item, Mapping):
                continue
            identifier = item.get("identifier") or item.get("references")
            if not identifier:
                continue
            images.append(
                {
                    "source": self.source,
                    "source_record_id": f"{record.get('key')}:{index}",
                    "url": str(identifier),
                    "identifier": _string_or_none(item.get("identifier")),
                    "thumbnail_url": _string_or_none(item.get("thumbnail")),
                    "title": _string_or_none(item.get("title")),
                    "description": _string_or_none(item.get("description")),
                    "creator": _string_or_none(item.get("creator")),
                    "publisher": _string_or_none(item.get("publisher")),
                    "license": _string_or_none(item.get("license")),
                    "mime_type": _string_or_none(item.get("type")),
                    "references": _string_or_none(item.get("references")),
                }
            )
        return tuple(images)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    text = _string_or_none(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
