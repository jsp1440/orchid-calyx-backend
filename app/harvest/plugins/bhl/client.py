"""HTTP client for the Biodiversity Heritage Library API v2."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import random
import time
from typing import Any, Mapping

import requests


@dataclass(slots=True)
class BHLClient:
    api_key: str | None = None
    base_url: str = "https://www.biodiversitylibrary.org/api2/httpquery.ashx"
    timeout_seconds: float = 30.0
    max_attempts: int = 4
    backoff_seconds: float = 0.5
    min_interval_seconds: float = 0.5
    session: requests.Session | None = None
    _last_request_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.getenv("BHL_API_KEY")
        if self.session is None:
            self.session = requests.Session()

    def item_search(self, *, search_term: str, page: int = 1) -> Mapping[str, Any]:
        return self._request("ItemSearch", searchterm=search_term, page=page)

    def part_search(self, *, search_term: str, page: int = 1) -> Mapping[str, Any]:
        return self._request("PartSearch", searchterm=search_term, page=page)

    def page_search(self, *, search_term: str, page: int = 1) -> Mapping[str, Any]:
        return self._request("PageSearch", searchterm=search_term, page=page)

    def item_metadata(self, item_id: int) -> Mapping[str, Any]:
        return self._request("GetItemMetadata", id=item_id, pages="t", ocr="t", parts="t")

    def part_metadata(self, part_id: int) -> Mapping[str, Any]:
        return self._request("GetPartMetadata", id=part_id)

    def page_ocr(self, page_id: int) -> Mapping[str, Any]:
        return self._request("GetPageOcrText", pageid=page_id)

    def page_images(self, page_id: int) -> Mapping[str, Any]:
        return self._request("GetPageImages", pageid=page_id)

    def item_pdfs(self, item_id: int) -> Mapping[str, Any]:
        return self._request("GetItemPDFs", id=item_id)

    def _request(self, operation: str, **params: Any) -> Mapping[str, Any]:
        if not self.api_key:
            raise RuntimeError("BHL_API_KEY is required")
        assert self.session is not None
        request_params = {"op": operation, "apikey": self.api_key, "format": "json", **params}
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._rate_limit()
            try:
                response = self.session.get(
                    self.base_url,
                    params=request_params,
                    timeout=self.timeout_seconds,
                    headers={"Accept": "application/json", "User-Agent": "Orchid-Continuum-Harvester/2"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, Mapping):
                    raise ValueError("BHL returned a non-object payload")
                status = str(payload.get("Status", "ok")).lower()
                if status not in {"ok", "success"}:
                    raise ValueError(str(payload.get("ErrorMessage") or payload.get("Status")))
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                delay = self.backoff_seconds * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_seconds)
                time.sleep(delay)
        raise RuntimeError("BHL request failed") from last_error

    def _rate_limit(self) -> None:
        now = time.monotonic()
        remaining = self.min_interval_seconds - (now - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()
