"""iNaturalist observation harvester plugin."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ...base import BaseHarvester
from ...models import HarvestPage
from ...registry import registry
from .client import INaturalistClient


@registry.register
class INaturalistHarvester(BaseHarvester):
    """Harvest orchid observations and licensed photographs from iNaturalist."""

    source = "inaturalist"

    def __init__(self, *, persistence: Any, checkpoints: Any, metrics: Any) -> None:
        super().__init__(persistence=persistence, checkpoints=checkpoints, metrics=metrics)
        self.client = INaturalistClient()

    def fetch_page(self, checkpoint: Mapping[str, Any] | None = None) -> HarvestPage:
        state = dict(checkpoint or {})
        page = int(state.get("page", 1))
        per_page = min(200, max(1, int(state.get("per_page", 100))))
        payload = self.client.observations(
            page=page,
            per_page=per_page,
            taxon_id=_int_or_none(state.get("taxon_id")),
            taxon_name=_string_or_none(state.get("taxon_name")) or "Orchidaceae",
            quality_grade=_string_or_none(state.get("quality_grade")),
            photos=_bool_or_none(state.get("photos")),
            captive=_bool_or_none(state.get("captive")),
        )
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("iNaturalist payload results must be a list")
        records = tuple(item for item in raw_results if isinstance(item, Mapping))
        total = _int_or_none(payload.get("total_results"))
        processed = (page - 1) * per_page + len(records)
        end = not records or len(records) < per_page or (total is not None and processed >= total)
        return HarvestPage(
            records=records,
            next_checkpoint={
                "page": page + 1,
                "per_page": per_page,
                "taxon_id": state.get("taxon_id"),
                "taxon_name": state.get("taxon_name") or "Orchidaceae",
                "quality_grade": state.get("quality_grade"),
                "photos": state.get("photos"),
                "captive": state.get("captive"),
                "processed": processed,
            },
            end_of_stream=end,
        )

    def normalize(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        observation_id = record.get("id")
        taxon = record.get("taxon") if isinstance(record.get("taxon"), Mapping) else {}
        scientific_name = taxon.get("name") or record.get("species_guess")
        if observation_id is None:
            raise ValueError("iNaturalist observation is missing id")
        if not scientific_name:
            raise ValueError("iNaturalist observation is missing scientific name")
        location = _coordinates(record.get("location"))
        user = record.get("user") if isinstance(record.get("user"), Mapping) else {}
        place = record.get("place_guess") or record.get("private_place_guess")
        uri = record.get("uri") or f"https://www.inaturalist.org/observations/{observation_id}"
        normalized: dict[str, Any] = {
            "source": self.source,
            "source_record_id": str(observation_id),
            "scientific_name": str(scientific_name),
            "accepted_name": None,
            "taxon_key": _string_or_none(taxon.get("id")),
            "occurrence_id": str(observation_id),
            "basis_of_record": "HUMAN_OBSERVATION",
            "latitude": location[0],
            "longitude": location[1],
            "country_code": None,
            "locality": _string_or_none(place),
            "event_date": _datetime_or_none(record.get("observed_on_details", {}).get("date") if isinstance(record.get("observed_on_details"), Mapping) else record.get("observed_on")),
            "recorded_by": _string_or_none(user.get("login") or user.get("name")),
            "license": _string_or_none(record.get("license_code")),
            "references": str(uri),
            "quality_grade": _string_or_none(record.get("quality_grade")),
            "captive": bool(record.get("captive", False)),
            "positional_accuracy": record.get("positional_accuracy"),
            "images": tuple(self.extract_images(record)),
            "raw": dict(record),
        }
        return normalized

    def validate(self, record: Mapping[str, Any]) -> bool:
        return bool(record.get("source") == self.source and record.get("source_record_id") and record.get("scientific_name"))

    def extract_images(self, record: Mapping[str, Any]):
        photos = record.get("photos") or ()
        if not isinstance(photos, list):
            return ()
        images: list[Mapping[str, Any]] = []
        observation_id = record.get("id")
        for index, photo in enumerate(photos):
            if not isinstance(photo, Mapping):
                continue
            url = _string_or_none(photo.get("url"))
            if not url:
                continue
            original = url.replace("square.", "original.")
            large = url.replace("square.", "large.")
            attribution = _string_or_none(photo.get("attribution"))
            license_code = _string_or_none(photo.get("license_code"))
            images.append({
                "source": self.source,
                "source_record_id": f"{observation_id}:{photo.get('id', index)}",
                "url": original,
                "identifier": _string_or_none(photo.get("id")),
                "thumbnail_url": url,
                "title": None,
                "description": None,
                "creator": attribution,
                "publisher": "iNaturalist",
                "license": license_code,
                "mime_type": "image/jpeg",
                "references": f"https://www.inaturalist.org/photos/{photo.get('id')}" if photo.get("id") else None,
                "sizes": {"original": original, "large": large, "medium": url.replace("square.", "medium."), "small": url.replace("square.", "small."), "thumbnail": url},
            })
        return tuple(images)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def _coordinates(value: Any) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    try:
        latitude, longitude = str(value).split(",", 1)
        return float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None, None


def _datetime_or_none(value: Any) -> datetime | None:
    text = _string_or_none(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
