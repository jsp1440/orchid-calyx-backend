"""Minimal GBIF occurrence API client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import requests


@dataclass(slots=True)
class GBIFClient:
    base_url: str = "https://api.gbif.org/v1"
    timeout_seconds: float = 30.0
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def occurrence_search(
        self,
        *,
        offset: int = 0,
        limit: int = 300,
        taxon_key: str | None = None,
        scientific_name: str | None = None,
        media_type: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if taxon_key:
            params["taxon_key"] = taxon_key
        if scientific_name:
            params["scientific_name"] = scientific_name
        if media_type:
            params["media_type"] = media_type
        if extra:
            params.update(extra)

        response = self.session.get(
            f"{self.base_url.rstrip('/')}/occurrence/search",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("GBIF occurrence search returned a non-object payload")
        return payload
