"""Biodiversity Heritage Library literature harvester plugin."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ...base import BaseHarvester
from ...models import HarvestPage
from ...registry import registry
from .client import BHLClient


@registry.register
class BHLHarvester(BaseHarvester):
    """Harvest BHL books, articles, pages, OCR, plates, and PDF links."""

    source = "bhl"

    def __init__(self, *, persistence: Any, checkpoints: Any, metrics: Any) -> None:
        super().__init__(persistence=persistence, checkpoints=checkpoints, metrics=metrics)
        self.client = BHLClient()

    def authenticate(self) -> None:
        if not self.client.api_key:
            raise RuntimeError("BHL_API_KEY is required")

    def fetch_page(self, checkpoint: Mapping[str, Any] | None = None) -> HarvestPage:
        state = dict(checkpoint or {})
        page = max(1, int(state.get("page", 1)))
        entity = str(state.get("entity", "item")).lower()
        search_term = str(state.get("search_term") or "Orchidaceae")
        if entity == "part":
            payload = self.client.part_search(search_term=search_term, page=page)
        elif entity == "page":
            payload = self.client.page_search(search_term=search_term, page=page)
        else:
            entity = "item"
            payload = self.client.item_search(search_term=search_term, page=page)
        raw = payload.get("Result", [])
        if isinstance(raw, Mapping):
            records = (dict(raw, _bhl_entity=entity),)
        elif isinstance(raw, list):
            records = tuple(dict(item, _bhl_entity=entity) for item in raw if isinstance(item, Mapping))
        else:
            raise ValueError("BHL payload Result must be a list or object")
        end = not records
        return HarvestPage(
            records=records,
            next_checkpoint={
                "page": page + 1,
                "entity": entity,
                "search_term": search_term,
                "processed": int(state.get("processed", 0)) + len(records),
            },
            end_of_stream=end,
        )

    def normalize(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        entity = str(record.get("_bhl_entity") or _infer_entity(record))
        source_id = _source_id(record, entity)
        if source_id is None:
            raise ValueError("BHL record is missing a stable identifier")
        title = _text(record.get("Title") or record.get("FullTitle") or record.get("PageNumber") or record.get("Name"))
        stable_url = _text(record.get("ItemUrl") or record.get("PartUrl") or record.get("PageUrl") or record.get("Url"))
        authors = _authors(record)
        normalized: dict[str, Any] = {
            "source": self.source,
            "source_record_id": source_id,
            "object_type": entity,
            "title": title,
            "authors": authors,
            "publication": _text(record.get("PublicationDetails") or record.get("ContainerTitle") or record.get("Source")),
            "year": _integer(record.get("Year") or record.get("Date")),
            "volume": _text(record.get("Volume")),
            "issue": _text(record.get("Issue")),
            "page_numbers": _page_numbers(record),
            "doi": _identifier(record, "doi"),
            "stable_url": stable_url,
            "ocr_text": _text(record.get("OcrText") or record.get("OCRText")),
            "license": _text(record.get("LicenseUrl") or record.get("License")),
            "rights": _text(record.get("Rights") or record.get("CopyrightStatus")),
            "retrieved_at": datetime.now(timezone.utc),
            "media": tuple(self.extract_images(record)),
            "raw": {key: value for key, value in record.items() if key != "_bhl_entity"},
        }
        return normalized

    def validate(self, record: Mapping[str, Any]) -> bool:
        return bool(
            record.get("source") == self.source
            and record.get("source_record_id")
            and record.get("object_type") in {"item", "part", "page"}
        )

    def extract_images(self, record: Mapping[str, Any]):
        page_id = record.get("PageID") or record.get("PageId")
        full_image = _text(record.get("FullImageUrl") or record.get("ImageUrl"))
        thumbnail = _text(record.get("ThumbnailUrl"))
        media: list[Mapping[str, Any]] = []
        if full_image:
            media.append({
                "source": self.source,
                "source_record_id": f"page:{page_id}:image" if page_id else full_image,
                "media_type": "plate",
                "url": full_image,
                "thumbnail_url": thumbnail,
                "license": _text(record.get("LicenseUrl") or record.get("License")),
                "rights": _text(record.get("Rights") or record.get("CopyrightStatus")),
                "references": _text(record.get("PageUrl") or record.get("ItemUrl")),
            })
        pdf_url = _text(record.get("PdfUrl") or record.get("PDFUrl"))
        if pdf_url:
            media.append({
                "source": self.source,
                "source_record_id": f"item:{record.get('ItemID')}:pdf",
                "media_type": "pdf",
                "url": pdf_url,
                "license": _text(record.get("LicenseUrl") or record.get("License")),
                "rights": _text(record.get("Rights") or record.get("CopyrightStatus")),
                "references": _text(record.get("ItemUrl")),
            })
        return tuple(media)


def _infer_entity(record: Mapping[str, Any]) -> str:
    if record.get("PartID") or record.get("PartId"):
        return "part"
    if record.get("PageID") or record.get("PageId"):
        return "page"
    return "item"


def _source_id(record: Mapping[str, Any], entity: str) -> str | None:
    keys = {"item": ("ItemID", "ItemId"), "part": ("PartID", "PartId"), "page": ("PageID", "PageId")}[entity]
    for key in keys:
        if record.get(key) not in (None, ""):
            return str(record[key])
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(value: Any) -> int | None:
    text = _text(value)
    if text is None:
        return None
    for token in text.replace("/", " ").replace("-", " ").split():
        if len(token) == 4 and token.isdigit():
            return int(token)
    try:
        return int(text)
    except ValueError:
        return None


def _authors(record: Mapping[str, Any]) -> tuple[str, ...]:
    value = record.get("Authors") or record.get("Author")
    if isinstance(value, list):
        authors = []
        for item in value:
            if isinstance(item, Mapping):
                name = _text(item.get("Name") or item.get("FullName"))
            else:
                name = _text(item)
            if name:
                authors.append(name)
        return tuple(authors)
    text = _text(value)
    return () if text is None else (text,)


def _identifier(record: Mapping[str, Any], kind: str) -> str | None:
    identifiers = record.get("Identifiers")
    if isinstance(identifiers, list):
        for item in identifiers:
            if isinstance(item, Mapping) and str(item.get("IdentifierName", "")).lower() == kind:
                return _text(item.get("IdentifierValue"))
    return _text(record.get(kind.upper()) or record.get(kind))


def _page_numbers(record: Mapping[str, Any]) -> tuple[str, ...]:
    value = record.get("PageNumber") or record.get("Pages")
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, Mapping):
                number = _text(item.get("Number") or item.get("PageNumber"))
            else:
                number = _text(item)
            if number:
                result.append(number)
        return tuple(result)
    text = _text(value)
    return () if text is None else (text,)
