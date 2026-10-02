"""Bounded Firecrawl source reconnaissance for OC federation.

Firecrawl is used here to map source structure, not as a scientific authority
or a default bulk-ingestion mechanism.  The mapper is intentionally read-only:
it discovers URLs and classifies likely federation surfaces.  It never mutates
the knowledge graph or canonical taxonomy.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.source_federation.deadline import call_with_deadline, validate_deadline

FIRECRAWL_MAP_URL = "https://api.firecrawl.dev/v2/map"
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
#: Wall-clock bound on one paid Map call, enforced around the whole HTTP
#: exchange by ``call_with_deadline`` (httpx timeouts are per phase). The
#: ledger lease is sized from it (``SharedFirecrawlFederationService``), and
#: every httpx phase is also capped at it so an abandoned call ends on its own.
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0

_API_HINTS = ("api", "download", "dataset", "dwca", "darwin", "export", "bulk", "data")
_TERMS_HINTS = ("terms", "license", "licence", "copyright", "usage", "cite", "citation")
_TAXON_HINTS = ("taxon", "species", "name", "plant", "flora", "search")
_IDENTIFIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ipni_lsid", re.compile(r"urn:lsid:ipni\.org:[^\s/?#]+:[^\s/?#]+", re.IGNORECASE)),
    ("wfo_id", re.compile(r"\bwfo-\d{6,}\b", re.IGNORECASE)),
    ("doi", re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)),
)


@dataclass(frozen=True, slots=True)
class FederationSourceProfile:
    source_id: str
    root_url: str
    retrieved_at: str
    urls: tuple[str, ...]
    url_classes: Mapping[str, tuple[str, ...]]
    candidate_identifiers: Mapping[str, tuple[str, ...]]
    api_download_hints: tuple[str, ...]
    terms_license_hints: tuple[str, ...]
    preferred_ingestion: str
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FirecrawlFederationMapper:
    """Map a public site and emit a conservative federation source profile."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        endpoint: str = FIRECRAWL_MAP_URL,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        self._client = client
        self.endpoint = endpoint
        self.total_timeout_seconds = validate_deadline(total_timeout_seconds)

    def map_source(
        self,
        *,
        source_id: str,
        root_url: str,
        search: str | None = None,
        limit: int = DEFAULT_LIMIT,
        sitemap: str = "include",
        include_subdomains: bool = False,
    ) -> FederationSourceProfile:
        if not self.api_key:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is required for live federation mapping"
            )
        if limit < 1 or limit > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if sitemap not in {"include", "only", "skip"}:
            raise ValueError("sitemap must be one of: include, only, skip")

        parsed = urlparse(root_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("root_url must be an absolute http(s) URL")

        payload: dict[str, Any] = {
            "url": root_url,
            "limit": limit,
            "sitemap": sitemap,
            "includeSubdomains": include_subdomains,
        }
        if search:
            payload["search"] = search

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def exchange() -> Any:
            if self._client is not None:
                response = self._client.post(
                    self.endpoint, headers=headers, json=payload
                )
                response.raise_for_status()
                return response.json()
            with httpx.Client(timeout=self.total_timeout_seconds) as client:
                response = client.post(self.endpoint, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()

        # httpx timeouts are per phase; this bounds the whole exchange, so the
        # caller settles its ledger lease before the lease can expire.
        data = call_with_deadline(exchange, self.total_timeout_seconds)

        urls = tuple(_extract_links(data))
        return build_source_profile(
            source_id=source_id,
            root_url=root_url,
            urls=urls,
            firecrawl_response=data,
            request_parameters={
                "search": search,
                "limit": limit,
                "sitemap": sitemap,
                "include_subdomains": include_subdomains,
            },
        )


def _extract_links(payload: Mapping[str, Any]) -> Iterable[str]:
    raw = payload.get("links")
    if raw is None and isinstance(payload.get("data"), Mapping):
        raw = payload["data"].get("links")
    if not isinstance(raw, list):
        return ()

    links: list[str] = []
    for item in raw:
        if isinstance(item, str):
            url = item
        elif isinstance(item, Mapping):
            url = item.get("url") or item.get("href")
        else:
            url = None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            links.append(url)
    return tuple(dict.fromkeys(links))


def _classify_urls(urls: Iterable[str]) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {
        "api_or_download": [],
        "terms_or_license": [],
        "taxon_or_search": [],
        "other": [],
    }
    for url in urls:
        lowered = url.lower()
        if any(hint in lowered for hint in _API_HINTS):
            bucket = "api_or_download"
        elif any(hint in lowered for hint in _TERMS_HINTS):
            bucket = "terms_or_license"
        elif any(hint in lowered for hint in _TAXON_HINTS):
            bucket = "taxon_or_search"
        else:
            bucket = "other"
        buckets[bucket].append(url)
    return {key: tuple(values) for key, values in buckets.items()}


def _discover_identifiers(urls: Iterable[str]) -> dict[str, tuple[str, ...]]:
    found: dict[str, set[str]] = {name: set() for name, _ in _IDENTIFIER_PATTERNS}
    for url in urls:
        for name, pattern in _IDENTIFIER_PATTERNS:
            found[name].update(match.group(0) for match in pattern.finditer(url))
    return {key: tuple(sorted(values)) for key, values in found.items() if values}


def _preferred_ingestion(classes: Mapping[str, tuple[str, ...]]) -> str:
    if classes.get("api_or_download"):
        return (
            "review_discovered_machine_readable_routes_first; "
            "prefer sanctioned API/download/DwC-A over scraping"
        )
    return "reconnaissance_only; perform rights/terms review before any targeted scrape"


def build_source_profile(
    *,
    source_id: str,
    root_url: str,
    urls: Iterable[str],
    firecrawl_response: Mapping[str, Any] | None = None,
    request_parameters: Mapping[str, Any] | None = None,
) -> FederationSourceProfile:
    ordered_urls = tuple(dict.fromkeys(urls))
    classes = _classify_urls(ordered_urls)
    now = datetime.now(timezone.utc).isoformat()

    return FederationSourceProfile(
        source_id=source_id,
        root_url=root_url,
        retrieved_at=now,
        urls=ordered_urls,
        url_classes=classes,
        candidate_identifiers=_discover_identifiers(ordered_urls),
        api_download_hints=classes["api_or_download"],
        terms_license_hints=classes["terms_or_license"],
        preferred_ingestion=_preferred_ingestion(classes),
        provenance={
            "retrieval_method": "firecrawl_map",
            "retrieved_at": now,
            "request_parameters": dict(request_parameters or {}),
            "response_success": (
                firecrawl_response.get("success")
                if isinstance(firecrawl_response, Mapping)
                else None
            ),
            "scientific_status": "reconnaissance_only",
            "automatic_publication_allowed": False,
        },
    )
