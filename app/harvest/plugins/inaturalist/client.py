"""HTTP client for the iNaturalist observations API."""

from __future__ import annotations

from dataclasses import dataclass, field
import random
import time
from typing import Any, Mapping

import requests


@dataclass(slots=True)
class INaturalistClient:
    base_url: str = "https://api.inaturalist.org/v1"
    timeout_seconds: float = 30.0
    max_attempts: int = 4
    backoff_seconds: float = 0.5
    min_interval_seconds: float = 0.0
    session: requests.Session | None = None
    _last_request_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def observations(
        self,
        *,
        page: int = 1,
        per_page: int = 100,
        taxon_id: int | None = None,
        taxon_name: str | None = None,
        quality_grade: str | None = None,
        photos: bool | None = None,
        captive: bool | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page, "order_by": "id", "order": "asc"}
        if taxon_id is not None:
            params["taxon_id"] = taxon_id
        if taxon_name:
            params["taxon_name"] = taxon_name
        if quality_grade:
            params["quality_grade"] = quality_grade
        if photos is not None:
            params["photos"] = str(photos).lower()
        if captive is not None:
            params["captive"] = str(captive).lower()
        if extra:
            params.update(extra)
        return self._get("observations", params)

    def _get(self, path: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        assert self.session is not None
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._rate_limit()
            try:
                response = self.session.get(
                    f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                    params=dict(params),
                    timeout=self.timeout_seconds,
                    headers={"Accept": "application/json", "User-Agent": "Orchid-Continuum-Harvester/2"},
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, Mapping):
                    raise ValueError("iNaturalist returned a non-object payload")
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                delay = self.backoff_seconds * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_seconds)
                time.sleep(delay)
        raise RuntimeError("iNaturalist request failed") from last_error

    def _rate_limit(self) -> None:
        if self.min_interval_seconds <= 0:
            self._last_request_at = time.monotonic()
            return
        now = time.monotonic()
        remaining = self.min_interval_seconds - (now - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()
